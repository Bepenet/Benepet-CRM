import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, timedelta
from sqlalchemy import inspect, text, func
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Usuario, Cliente, Venda, ItemVenda

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'benepet_crm_secret_key_123')

base_uri = os.environ.get('DATABASE_URL', 'sqlite:///petcrm.db')

if base_uri.startswith("postgres://"):
    base_uri = base_uri.replace("postgres://", "postgresql://", 1)

if base_uri.startswith("postgresql://") and "sslmode" not in base_uri:
    if "?" in base_uri:
        base_uri += "&sslmode=require"
    else:
        base_uri += "?sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = base_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

_tabelas_verificadas = False

def garantir_colunas_novas():
    """Adiciona colunas novas em tabelas já existentes (SQLite ou Postgres),
    já que db.create_all() só cria tabelas que ainda não existem."""
    inspector = inspect(db.engine)

    colunas_venda = [c['name'] for c in inspector.get_columns('venda')]
    if 'prazo_pagamento' not in colunas_venda:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE venda ADD COLUMN prazo_pagamento VARCHAR(50)'))
            conn.commit()

    colunas_cliente = [c['name'] for c in inspector.get_columns('cliente')]
    with db.engine.connect() as conn:
        if 'contato_adiado_ate' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN contato_adiado_ate TIMESTAMP'))
            conn.commit()
        if 'contato_desconsiderado' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN contato_desconsiderado BOOLEAN DEFAULT FALSE'))
            conn.commit()

@app.before_request
def inicializar_banco_seguro():
    global _tabelas_verificadas
    if not _tabelas_verificadas:
        try:
            db.create_all()
            garantir_colunas_novas()
            if not Usuario.query.first():
                senha_criptografada = generate_password_hash('admin')
                usuario_padrao = Usuario(login='admin', senha=senha_criptografada)
                db.session.add(usuario_padrao)
                db.session.commit()
            _tabelas_verificadas = True
        except Exception as e:
            print(f"Aviso de verificação do banco em produção: {e}")

def usuario_esta_logado():
    return 'usuario' in session

@app.route('/')
def index():
    if usuario_esta_logado():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/criar_admin_forcado')
def criar_admin_forcado():
    try:
        db.drop_all()
        db.create_all()
        senha_criptografada = generate_password_hash('admin')
        usuario_padrao = Usuario(login='admin', senha=senha_criptografada)
        db.session.add(usuario_padrao)
        db.session.commit()
        return "Banco limpo e atualizado com novos campos!"
    except Exception as e:
        return f"Erro: {str(e)}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')

        try:
            user = Usuario.query.filter_by(login=usuario).first()
            if user and check_password_hash(user.senha, senha):
                session['usuario'] = user.login
                return redirect(url_for('dashboard'))
            else:
                flash('Usuário ou senha inválidos!', 'erro')
        except Exception as e:
            flash('Conexão instável com a base de dados. Tente novamente.', 'erro')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET'])
def dashboard():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    try:
        clientes_total = Cliente.query.count()
        vendas_total = Venda.query.count()
        todos_clientes = Cliente.query.all()
        total_contatos_pendentes = len([c for c in todos_clientes if c.precisa_contato])

        valor_total_vendido = db.session.query(func.sum(Venda.valor_total)).scalar() or 0

        vendido_por_produto = db.session.query(
            ItemVenda.produto, func.sum(ItemVenda.valor_subtotal)
        ).group_by(ItemVenda.produto).order_by(func.sum(ItemVenda.valor_subtotal).desc()).all()
    except Exception as e:
        clientes_total, vendas_total, total_contatos_pendentes = 0, 0, 0
        valor_total_vendido = 0
        vendido_por_produto = []

    return render_template('dashboard.html',
                           clientes_total=clientes_total,
                           vendas_total=vendas_total,
                           total_contatos_pendentes=total_contatos_pendentes,
                           valor_total_vendido=valor_total_vendido,
                           vendido_por_produto=vendido_por_produto,
                           usuario_logado=session['usuario'])

@app.route('/relatorios')
def relatorios():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    return render_template('relatorios.html')

@app.route('/relatorios/proximo-contato')
def relatorio_proximo_contato():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    todos_clientes = Cliente.query.all()
    clientes = sorted(todos_clientes, key=lambda c: c.proximo_contato)
    return render_template('relatorio_proximo_contato.html', clientes=clientes)

@app.route('/contatos-pendentes')
def contatos_pendentes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    todos_clientes = Cliente.query.all()
    pendentes = sorted(
        [c for c in todos_clientes if c.precisa_contato],
        key=lambda c: c.proximo_contato
    )
    desconsiderados = [c for c in todos_clientes if c.contato_desconsiderado]
    return render_template('contatos_pendentes.html', pendentes=pendentes, desconsiderados=desconsiderados)

@app.route('/clientes/<int:id>/adiar_contato', methods=['POST'])
def adiar_contato(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    cliente = Cliente.query.get_or_404(id)
    dias = int(request.form.get('dias', 1))
    cliente.contato_adiado_ate = datetime.utcnow() + timedelta(days=dias)
    cliente.contato_desconsiderado = False
    db.session.commit()
    flash(f'Lembrete de {cliente.nome} adiado.', 'sucesso')
    return redirect(url_for('contatos_pendentes'))

@app.route('/clientes/<int:id>/desconsiderar_contato', methods=['POST'])
def desconsiderar_contato(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    cliente = Cliente.query.get_or_404(id)
    cliente.contato_desconsiderado = True
    db.session.commit()
    flash(f'Lembrete de {cliente.nome} desconsiderado.', 'sucesso')
    return redirect(url_for('contatos_pendentes'))

@app.route('/clientes/<int:id>/reativar_contato', methods=['POST'])
def reativar_contato(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    cliente = Cliente.query.get_or_404(id)
    cliente.contato_desconsiderado = False
    cliente.contato_adiado_ate = None
    db.session.commit()
    flash(f'Lembrete de {cliente.nome} reativado.', 'sucesso')
    return redirect(url_for('contatos_pendentes'))

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome = request.form.get('nome')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        telefone = request.form.get('telefone')
        contato = request.form.get('contato')
        dias_aviso = int(request.form.get('dias_aviso', 30))
        data_cadastro_str = request.form.get('data_cadastro')

        if data_cadastro_str:
            data_cadastro = datetime.strptime(data_cadastro_str, '%Y-%m-%d')
        else:
            data_cadastro = datetime.utcnow()

        novo_cliente = Cliente(
            nome=nome,
            cpf_cnpj=cpf_cnpj,
            endereco=endereco,
            telefone=telefone,
            contato=contato,
            data_cadastro=data_cadastro,
            dias_aviso=dias_aviso,
            periodo_retorno=dias_aviso
        )
        db.session.add(novo_cliente)
        db.session.commit()
        flash('Cliente cadastrado com sucesso!', 'sucesso')
        return redirect(url_for('clientes'))

    todos_clientes = Cliente.query.all()
    hoje_formatado = datetime.now().strftime('%Y-%m-%d')
    return render_template('clientes.html', clientes=todos_clientes, hoje=hoje_formatado)

@app.route('/clientes/<int:id>', methods=['GET', 'POST'])
def detalhe_cliente(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    cliente = Cliente.query.get_or_404(id)

    if request.method == 'POST':
        cliente.nome = request.form.get('nome')
        cliente.cpf_cnpj = request.form.get('cpf_cnpj')
        cliente.endereco = request.form.get('endereco')
        cliente.telefone = request.form.get('telefone')
        cliente.contato = request.form.get('contato')
        dias_aviso = int(request.form.get('dias_aviso', 30))
        cliente.dias_aviso = dias_aviso
        cliente.periodo_retorno = dias_aviso

        db.session.commit()
        flash('Dados do cliente atualizados com sucesso!', 'sucesso')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    historico_vendas = sorted(cliente.vendas, key=lambda v: v.data, reverse=True)
    return render_template('cliente_detalhe.html', cliente=cliente, vendas=historico_vendas)

@app.route('/vendas')
def vendas():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    clientes = Cliente.query.all()
    historico_vendas = Venda.query.order_by(Venda.data.desc()).all()
    return render_template('vendas.html', clientes=clientes, vendas=historico_vendas)

@app.route('/usuarios', methods=['GET', 'POST'])
def usuarios():
    if not usuario_esta_logado() or session['usuario'] != 'admin':
        flash('Acesso restrito apenas para o administrador!', 'erro')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        novo_login = request.form.get('usuario')
        nova_senha = request.form.get('senha')

        if Usuario.query.filter_by(login=novo_login).first():
            flash('Esse nome de usuário já existe!', 'erro')
        else:
            senha_segura = generate_password_hash(nova_senha)
            novo_user = Usuario(login=novo_login, senha=senha_segura)
            db.session.add(novo_user)
            db.session.commit()
            flash('Usuário criado com sucesso!', 'sucesso')
        return redirect(url_for('usuarios'))

    lista_usuarios = Usuario.query.all()
    return render_template('usuarios.html', usuarios=lista_usuarios)

@app.route('/salvar_venda_multipla', methods=['POST'])
def salvar_venda_multipla():
    if not usuario_esta_logado():
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.get_json()
    cliente_id = dados.get('cliente_id')
    data_str = dados.get('data')
    valor_total = dados.get('valor_total')
    itens = dados.get('itens')
    prazo_pagamento = dados.get('prazo_pagamento')

    data_venda = datetime.strptime(data_str, '%Y-%m-%d') if data_str else datetime.utcnow()

    try:
        nova_venda = Venda(cliente_id=cliente_id, data=data_venda, valor_total=valor_total, prazo_pagamento=prazo_pagamento)
        db.session.add(nova_venda)
        db.session.flush()

        for item in itens:
            novo_item = ItemVenda(
                venda_id=nova_venda.id,
                produto=item['produto'],
                quantidade=int(item['quantidade']),
                valor_unitario=float(item['valor_unitario']),
                valor_subtotal=float(item['valor_subtotal'])
            )
            db.session.add(novo_item)

        db.session.commit()
        return jsonify({"mensagem": "Venda gravada com sucesso!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 500

@app.route('/vendas/relatorio')
def relatorio_vendas():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    vendas = Venda.query.order_by(Venda.data.desc()).all()
    return render_template('detalhe_vendas.html', vendas=vendas)

@app.route('/venda/detalhar/<int:id>')
def detalhar_venda(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda = Venda.query.get(id)
    if not venda:
        return "Venda não encontrada", 404

    itens = venda.itens
    return render_template('detalhe_vendas.html', venda=venda, itens=itens, modo_visualizacao=True)

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
