import os
import unicodedata
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, timedelta
from sqlalchemy import inspect, text, func
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Usuario, Cliente, Venda, ItemVenda, Prospeccao, HistoricoProspeccao

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'benepet_crm_secret_key_123')

# Nomes "oficiais" dos produtos e variações já lançadas que devem ser somadas juntas
# (cobre diferenças de maiúscula/minúscula, acento e singular/plural)
MAPA_PRODUTOS = {
    'TAPETE USO INTERNO': ['TAPETE USO INTERNO'],
    'TAPETE BAG REVENDA': ['TAPETE BAG REVENDA', 'TAPETE BAG REVENDAS'],
    'AREIA SILICA': ['AREIA SILICA'],
    'CATA CACA': ['CATA CACA'],
}

def normalizar_texto(texto):
    """Remove acentos e deixa em maiúsculas, para comparar nomes de forma consistente."""
    if not texto:
        return ''
    sem_acento = ''.join(
        c for c in unicodedata.normalize('NFKD', texto)
        if not unicodedata.combining(c)
    )
    return sem_acento.strip().upper()

def nome_canonico_produto(nome):
    """Devolve o nome padrão do produto, agrupando variações conhecidas."""
    normalizado = normalizar_texto(nome)
    for canonico, variantes in MAPA_PRODUTOS.items():
        if normalizado in variantes:
            return canonico
    return normalizado or 'SEM NOME'

def formatar_moeda(valor):
    """Formata um número no padrão brasileiro: milhar com ponto, decimal com vírgula."""
    return '{:,.2f}'.format(valor or 0).replace(',', 'X').replace('.', ',').replace('X', '.')

# Número que recebe o aviso de vendas confirmadas para emissão de NF (com DDI+DDD)
WHATSAPP_NF_NUMERO = os.environ.get('WHATSAPP_NF_NUMERO', '5547988139107')

def montar_link_whatsapp_nf(venda):
    """Monta o link do WhatsApp (wa.me) com os dados da venda prontos para gerar a NF."""
    cliente = venda.cliente
    linhas = [
        "📄 *Nova venda confirmada - gerar NF*",
        f"Cliente (Razão Social): {cliente.nome}",
    ]
    if cliente.nome_fantasia:
        linhas.append(f"Nome Fantasia: {cliente.nome_fantasia}")
    linhas.append(f"CNPJ/CPF: {cliente.cpf_cnpj or 'não informado'}")
    if cliente.endereco:
        linhas.append(f"Endereço: {cliente.endereco}")
    linhas.append(f"Data: {venda.data_efetiva.strftime('%d/%m/%Y')}")
    linhas.append(f"Prazo de Pagamento: {venda.prazo_pagamento or 'não informado'}")
    linhas.append("")
    linhas.append("Itens:")
    for item in venda.itens:
        linhas.append(f"- {item.produto} x{item.quantidade} = R$ {formatar_moeda(item.valor_subtotal)}")
    linhas.append("")
    linhas.append(f"*Total: R$ {formatar_moeda(venda.valor_total)}*")

    mensagem = "\n".join(linhas)
    return f"https://wa.me/{WHATSAPP_NF_NUMERO}?text={quote(mensagem)}"

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
    with db.engine.connect() as conn:
        if 'prazo_pagamento' not in colunas_venda:
            conn.execute(text('ALTER TABLE venda ADD COLUMN prazo_pagamento VARCHAR(50)'))
            conn.commit()
        if 'tipo' not in colunas_venda:
            conn.execute(text("ALTER TABLE venda ADD COLUMN tipo VARCHAR(20) DEFAULT 'Normal'"))
            conn.commit()
        if 'status' not in colunas_venda:
            conn.execute(text("ALTER TABLE venda ADD COLUMN status VARCHAR(20) DEFAULT 'Confirmada'"))
            conn.commit()
        if 'data_confirmacao' not in colunas_venda:
            conn.execute(text('ALTER TABLE venda ADD COLUMN data_confirmacao TIMESTAMP'))
            conn.commit()

    colunas_cliente = [c['name'] for c in inspector.get_columns('cliente')]
    with db.engine.connect() as conn:
        if 'contato_adiado_ate' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN contato_adiado_ate TIMESTAMP'))
            conn.commit()
        if 'contato_desconsiderado' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN contato_desconsiderado BOOLEAN DEFAULT FALSE'))
            conn.commit()
        if 'vendedor' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN vendedor VARCHAR(100)'))
            conn.commit()
        if 'nome_fantasia' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN nome_fantasia VARCHAR(100)'))
            conn.commit()

    colunas_usuario = [c['name'] for c in inspector.get_columns('usuario')]
    if 'precisa_trocar_senha' not in colunas_usuario:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE usuario ADD COLUMN precisa_trocar_senha BOOLEAN DEFAULT TRUE'))
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
                usuario_padrao = Usuario(login='admin', senha=senha_criptografada, precisa_trocar_senha=True)
                db.session.add(usuario_padrao)
                db.session.commit()
            _tabelas_verificadas = True
        except Exception as e:
            print(f"Aviso de verificação do banco em produção: {e}")

def usuario_esta_logado():
    return 'usuario' in session

@app.before_request
def forcar_troca_senha():
    if not usuario_esta_logado():
        return
    if request.endpoint in ('trocar_senha', 'logout', 'static', None):
        return
    try:
        user = Usuario.query.filter_by(login=session['usuario']).first()
        if user and user.precisa_trocar_senha:
            return redirect(url_for('trocar_senha'))
    except Exception:
        pass

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

@app.route('/trocar-senha', methods=['GET', 'POST'])
def trocar_senha():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    user = Usuario.query.filter_by(login=session['usuario']).first()

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha')
        confirmar_senha = request.form.get('confirmar_senha')

        if not nova_senha or len(nova_senha) < 4:
            flash('A nova senha precisa ter pelo menos 4 caracteres.', 'erro')
        elif nova_senha != confirmar_senha:
            flash('As senhas não coincidem.', 'erro')
        else:
            user.senha = generate_password_hash(nova_senha)
            user.precisa_trocar_senha = False
            db.session.commit()
            flash('Senha alterada com sucesso!', 'sucesso')
            return redirect(url_for('dashboard'))

    primeiro_acesso = user.precisa_trocar_senha if user else True
    return render_template('trocar_senha.html', primeiro_acesso=primeiro_acesso)

@app.route('/dashboard', methods=['GET'])
def dashboard():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    try:
        clientes_total = Cliente.query.count()
        vendas_total = Venda.query.filter_by(status='Confirmada').count()
        todos_clientes = Cliente.query.all()
        total_contatos_pendentes = len([c for c in todos_clientes if c.precisa_contato])
        total_consignacoes_pendentes = Venda.query.filter_by(tipo='Consignado', status='Pendente').count()
        total_prospeccoes = len([p for p in Prospeccao.query.all() if p.ativa])

        valor_total_vendido = db.session.query(func.sum(Venda.valor_total)).filter(Venda.status == 'Confirmada').scalar() or 0

        itens_vendidos = db.session.query(ItemVenda.produto, ItemVenda.quantidade, ItemVenda.valor_subtotal)\
            .join(Venda).filter(Venda.status == 'Confirmada').all()
        totais_por_produto = {}
        for produto, quantidade, subtotal in itens_vendidos:
            canonico = nome_canonico_produto(produto)
            if canonico not in totais_por_produto:
                totais_por_produto[canonico] = {'quantidade': 0, 'valor': 0}
            totais_por_produto[canonico]['quantidade'] += quantidade
            totais_por_produto[canonico]['valor'] += subtotal
        vendido_por_produto = sorted(totais_por_produto.items(), key=lambda item: item[1]['valor'], reverse=True)
        for produto, dados in vendido_por_produto:
            dados['quantidade_fmt'] = '{:,}'.format(dados['quantidade']).replace(',', '.')
            dados['valor_fmt'] = formatar_moeda(dados['valor'])

        valor_total_vendido_fmt = formatar_moeda(valor_total_vendido)
    except Exception as e:
        clientes_total, vendas_total, total_contatos_pendentes, total_consignacoes_pendentes = 0, 0, 0, 0
        total_prospeccoes = 0
        valor_total_vendido = 0
        valor_total_vendido_fmt = formatar_moeda(0)
        vendido_por_produto = []

    return render_template('dashboard.html',
                           clientes_total=clientes_total,
                           vendas_total=vendas_total,
                           total_contatos_pendentes=total_contatos_pendentes,
                           total_consignacoes_pendentes=total_consignacoes_pendentes,
                           total_prospeccoes=total_prospeccoes,
                           valor_total_vendido=valor_total_vendido,
                           valor_total_vendido_fmt=valor_total_vendido_fmt,
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

@app.route('/relatorios/vendas-por-vendedor')
def relatorio_vendas_por_vendedor():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    vendas = Venda.query.join(Cliente).filter(Venda.status == 'Confirmada').all()
    totais = {}
    for venda in vendas:
        vendedor = venda.cliente.vendedor or 'Sem vendedor definido'
        if vendedor not in totais:
            totais[vendedor] = {'quantidade_vendas': 0, 'valor': 0}
        totais[vendedor]['quantidade_vendas'] += 1
        totais[vendedor]['valor'] += venda.valor_total

    for vendedor, dados in totais.items():
        dados['valor_fmt'] = formatar_moeda(dados['valor'])

    resultado = sorted(totais.items(), key=lambda item: item[1]['valor'], reverse=True)
    return render_template('relatorio_vendas_vendedor.html', vendedores=resultado)

@app.route('/relatorios/vendas-por-mes')
def relatorio_vendas_por_mes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    meses_pt = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

    vendas = Venda.query.filter_by(status='Confirmada').all()
    totais = {}
    for venda in vendas:
        chave = (venda.data_efetiva.year, venda.data_efetiva.month)
        if chave not in totais:
            totais[chave] = {'quantidade_vendas': 0, 'valor': 0}
        totais[chave]['quantidade_vendas'] += 1
        totais[chave]['valor'] += venda.valor_total

    for chave, dados in totais.items():
        dados['valor_fmt'] = formatar_moeda(dados['valor'])
        dados['label'] = f"{meses_pt[chave[1]]}/{chave[0]}"

    resultado = sorted(totais.items(), key=lambda item: item[0], reverse=True)
    return render_template('relatorio_vendas_mes.html', meses=resultado)

@app.route('/consignacoes-pendentes')
def consignacoes_pendentes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    pendentes = Venda.query.filter_by(tipo='Consignado', status='Pendente').order_by(Venda.data.desc()).all()
    return render_template('consignacoes_pendentes.html', pendentes=pendentes)

@app.route('/vendas/<int:id>/confirmar_consignacao', methods=['POST'])
def confirmar_consignacao(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda = Venda.query.get_or_404(id)
    if venda.tipo == 'Consignado' and venda.status == 'Pendente':
        venda.status = 'Confirmada'
        venda.data_confirmacao = datetime.utcnow()
        db.session.commit()
        flash(f'Consignação #{venda.id} confirmada como venda!', 'sucesso')
        flash(montar_link_whatsapp_nf(venda), 'whatsapp_link')
    return redirect(url_for('consignacoes_pendentes'))

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
        nome_fantasia = request.form.get('nome_fantasia')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        telefone = request.form.get('telefone')
        contato = request.form.get('contato')
        vendedor = request.form.get('vendedor')
        dias_aviso = int(request.form.get('dias_aviso', 30))
        data_cadastro_str = request.form.get('data_cadastro')

        if data_cadastro_str:
            data_cadastro = datetime.strptime(data_cadastro_str, '%Y-%m-%d')
        else:
            data_cadastro = datetime.utcnow()

        novo_cliente = Cliente(
            nome=nome,
            nome_fantasia=nome_fantasia,
            cpf_cnpj=cpf_cnpj,
            endereco=endereco,
            telefone=telefone,
            contato=contato,
            vendedor=vendedor,
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
        cliente.nome_fantasia = request.form.get('nome_fantasia')
        cliente.cpf_cnpj = request.form.get('cpf_cnpj')
        cliente.endereco = request.form.get('endereco')
        cliente.telefone = request.form.get('telefone')
        cliente.contato = request.form.get('contato')
        cliente.vendedor = request.form.get('vendedor')
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
            novo_user = Usuario(login=novo_login, senha=senha_segura, precisa_trocar_senha=True)
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
    tipo_venda = dados.get('tipo_venda', 'Normal')

    data_venda = datetime.strptime(data_str, '%Y-%m-%d') if data_str else datetime.utcnow()
    status_venda = 'Pendente' if tipo_venda == 'Consignado' else 'Confirmada'

    try:
        nova_venda = Venda(
            cliente_id=cliente_id,
            data=data_venda,
            valor_total=valor_total,
            prazo_pagamento=prazo_pagamento,
            tipo=tipo_venda,
            status=status_venda
        )
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

        link_whatsapp = None
        if nova_venda.status == 'Confirmada':
            link_whatsapp = montar_link_whatsapp_nf(nova_venda)

        return jsonify({"mensagem": "Venda gravada com sucesso!", "link_whatsapp": link_whatsapp}), 200
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

TIPOS_HISTORICO = ['WhatsApp', 'Telefone', 'E-mail', 'Amostra', 'Visita', 'Negociação', 'Outro']

@app.route('/prospeccoes', methods=['GET', 'POST'])
def prospeccoes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        contato = request.form.get('contato')
        vendedor = request.form.get('vendedor')
        observacoes = request.form.get('observacoes')
        status = request.form.get('status', 'Em andamento')
        proxima_data_str = request.form.get('proxima_acao_data')
        proxima_descricao = request.form.get('proxima_acao_descricao')

        proxima_data = None
        if proxima_data_str:
            proxima_data = datetime.strptime(proxima_data_str, '%Y-%m-%d')

        nova = Prospeccao(
            nome=nome,
            telefone=telefone,
            contato=contato,
            vendedor=vendedor,
            observacoes=observacoes,
            status=status,
            data_cadastro=datetime.utcnow(),
            proxima_acao_data=proxima_data,
            proxima_acao_descricao=proxima_descricao,
        )
        db.session.add(nova)
        db.session.commit()
        flash(f'Prospecção "{nome}" cadastrada com sucesso!', 'sucesso')
        return redirect(url_for('prospeccoes'))

    filtro = request.args.get('status', 'Ativas')
    todas = Prospeccao.query.order_by(Prospeccao.data_cadastro.desc()).all()
    if filtro == 'Ativas':
        lista = [p for p in todas if p.ativa]
    elif filtro == 'Convertido':
        lista = [p for p in todas if p.status == 'Convertido']
    elif filtro == 'Perdido':
        lista = [p for p in todas if p.status == 'Perdido']
    else:
        lista = todas

    hoje_formatado = datetime.now().strftime('%Y-%m-%d')
    return render_template('prospeccoes.html',
                           prospeccoes=lista,
                           todas=todas,
                           filtro=filtro,
                           statuses=['Em andamento', 'Amostra enviada', 'Negociação', 'Convertido', 'Perdido'],
                           hoje=hoje_formatado)

@app.route('/prospeccoes/<int:id>', methods=['GET', 'POST'])
def detalhe_prospeccao(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    prospeccao = Prospeccao.query.get_or_404(id)

    if request.method == 'POST':
        prospeccao.nome = request.form.get('nome')
        prospeccao.telefone = request.form.get('telefone')
        prospeccao.contato = request.form.get('contato')
        prospeccao.vendedor = request.form.get('vendedor')
        prospeccao.observacoes = request.form.get('observacoes')
        prospeccao.status = request.form.get('status')
        proxima_data_str = request.form.get('proxima_acao_data')
        prospeccao.proxima_acao_data = datetime.strptime(proxima_data_str, '%Y-%m-%d') if proxima_data_str else None
        prospeccao.proxima_acao_descricao = request.form.get('proxima_acao_descricao')
        db.session.commit()
        flash('Dados da prospecção atualizados!', 'sucesso')
        return redirect(url_for('detalhe_prospeccao', id=prospeccao.id))

    historico = sorted(prospeccao.historicos, key=lambda h: h.data, reverse=True)
    return render_template('prospeccao_detalhe.html',
                           p=prospeccao,
                           historico=historico,
                           statuses=['Em andamento', 'Amostra enviada', 'Negociação', 'Convertido', 'Perdido'],
                           tipos_historico=TIPOS_HISTORICO,
                           hoje=datetime.now().strftime('%Y-%m-%d'))

@app.route('/prospeccoes/<int:id>/historico', methods=['POST'])
def adicionar_historico(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    prospeccao = Prospeccao.query.get_or_404(id)
    data_str = request.form.get('data')
    tipo = request.form.get('tipo', 'Outro')
    descricao = request.form.get('descricao')

    if not descricao:
        flash('Descreva a ação realizada.', 'erro')
        return redirect(url_for('detalhe_prospeccao', id=prospeccao.id))

    data = datetime.strptime(data_str, '%Y-%m-%d') if data_str else datetime.utcnow()

    novo = HistoricoProspeccao(
        prospeccao_id=prospeccao.id,
        data=data,
        tipo=tipo,
        descricao=descricao,
    )
    db.session.add(novo)
    db.session.commit()
    flash('Ação registrada no histórico!', 'sucesso')
    return redirect(url_for('detalhe_prospeccao', id=prospeccao.id))

@app.route('/historico/<int:id>/excluir', methods=['POST'])
def excluir_historico(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    historico = HistoricoProspeccao.query.get_or_404(id)
    prospeccao_id = historico.prospeccao_id
    db.session.delete(historico)
    db.session.commit()
    flash('Registro do histórico excluído.', 'sucesso')
    return redirect(url_for('detalhe_prospeccao', id=prospeccao_id))

@app.route('/prospeccoes/<int:id>/converter', methods=['POST'])
def converter_prospeccao(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    prospeccao = Prospeccao.query.get_or_404(id)
    if prospeccao.cliente_id:
        flash('Essa prospecção já foi convertida em cliente.', 'erro')
        return redirect(url_for('detalhe_prospeccao', id=prospeccao.id))

    cliente = Cliente(
        nome=prospeccao.nome,
        telefone=prospeccao.telefone,
        contato=prospeccao.contato,
        vendedor=prospeccao.vendedor,
        data_cadastro=datetime.utcnow(),
        dias_aviso=30,
        periodo_retorno=30,
    )
    db.session.add(cliente)
    db.session.flush()
    prospeccao.cliente_id = cliente.id
    prospeccao.status = 'Convertido'
    db.session.commit()
    flash(f'Prospecção convertida! Cliente "{cliente.nome}" criado.', 'sucesso')
    return redirect(url_for('detalhe_cliente', id=cliente.id))

@app.route('/prospeccoes/<int:id>/excluir', methods=['POST'])
def excluir_prospeccao(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    prospeccao = Prospeccao.query.get_or_404(id)
    nome = prospeccao.nome
    for h in prospeccao.historicos:
        db.session.delete(h)
    db.session.delete(prospeccao)
    db.session.commit()
    flash(f'Prospecção "{nome}" excluída.', 'sucesso')
    return redirect(url_for('prospeccoes'))

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
