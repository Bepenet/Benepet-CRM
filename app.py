import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime
from models import db, Usuario, Cliente, Venda, ItemVenda

app = Flask(__name__)

# Configurações básicas de Segurança
app.config['SECRET_KEY'] = 'benepet_crm_secret_key_123'

# 1️⃣ CAPTURA E CONFIGURAÇÃO DA STRING DE CONEXÃO DO BANCO
base_uri = os.environ.get('DATABASE_URL', 'sqlite:///petcrm.db')

# Correção essencial para o padrão exigido pelo SQLAlchemy (de postgres:// para postgresql://)
if base_uri.startswith("postgres://"):
    base_uri = base_uri.replace("postgres://", "postgresql://", 1)

# Se for PostgreSQL (Render), garante os parâmetros corretos de SSL exigidos na nuvem
if base_uri.startswith("postgresql://") and "sslmode" not in base_uri:
    if "?" in base_uri:
        base_uri += "&sslmode=require"
    else:
        base_uri += "?sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = base_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializa o framework do banco de dados no Flask
db.init_app(app)

# 2️⃣ INICIALIZAÇÃO SEGURA: Executa a validação do banco apenas no primeiro acesso real
@app.before_request
def inicializar_banco_seguro():
    # Removemos o bloco de inicialização do fluxo de carregamento principal do Gunicorn
    # para evitar que conflitos de portas derrubem a aplicação na subida
    app.before_request_funcs[None].remove(inicializar_banco_seguro)
    try:
        db.create_all()
        # Garante a conta administrativa padrão se o banco estiver vazio
        if not Usuario.query.first():
            usuario_padrao = Usuario(login='admin', senha='admin')
            db.session.add(usuario_padrao)
            db.session.commit()
    except Exception as e:
        print(f"Alerta na verificação automática de tabelas: {e}")

# --- FUNÇÃO AUXILIAR DE PROTEÇÃO DE ACESSO ---
def usuario_esta_logado():
    return 'usuario' in session

# --- ROTAS DO SISTEMA ---

@app.route('/')
def index():
    if usuario_esta_logado():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/criar_admin_forcado')
def criar_admin_forcado():
    try:
        db.create_all()
        existe = Usuario.query.filter_by(login='admin').first()
        if not existe:
            usuario_padrao = Usuario(login='admin', senha='admin')
            db.session.add(usuario_padrao)
            db.session.commit()
            return "Usuário 'admin' gerado com sucesso no PostgreSQL! Pode retornar para /login."
        return "O usuário 'admin' já consta na base de dados ativa."
    except Exception as e:
        return f"Falha crítica ao tentar forçar criação: {str(e)}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')
        
        try:
            user = Usuario.query.filter_by(login=usuario, senha=senha).first()
            if user:
                session['usuario'] = user.login
                return redirect(url_for('dashboard'))
            else:
                flash('Usuário ou senha inválidos!', 'erro')
        except Exception as e:
            flash('Conexão instável com a base de dados. Aguarde um instante e tente novamente.', 'erro')
            print(f"Erro de autenticação: {e}")
            
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
        clientes = Cliente.query.all()
    except Exception as e:
        print(f"Erro ao carregar dados do dashboard: {e}")
        clientes_total, vendas_total, clientes = 0, 0, []
    
    return render_template('dashboard.html', 
                           clientes_total=clientes_total, 
                           vendas_total=vendas_total, 
                           clientes=clientes,
                           usuario_logado=session['usuario'])

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        produto = request.form.get('produto')
        periodo = int(request.form.get('periodo', 30))
        
        novo_cliente = Cliente(
            nome=nome,
            telefone=telefone,
            produto=produto,
            periodo_retorno=periodo,
            data_cadastro=datetime.utcnow()
        )
        db.session.add(novo_cliente)
        db.session.commit()
        flash('Cliente cadastrado com sucesso!', 'sucesso')
        return redirect(url_for('clientes'))
        
    todos_clientes = Cliente.query.all()
    return render_template('clientes.html', clientes=todos_clientes)

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
            novo_user = Usuario(login=novo_login, senha=nova_senha)
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
    if not dados:
        return jsonify({"erro": "Dados inválidos"}), 400
        
    cliente_id = dados.get('cliente_id')
    data_str = dados.get('data')
    valor_total = dados.get('valor_total')
    itens = dados.get('itens')
    
    data_venda = datetime.strptime(data_str, '%Y-%m-%d') if data_str else datetime.utcnow()
    
    try:
        nova_venda = Venda(
            cliente_id=cliente_id,
            data=data_venda,
            valor_total=valor_total
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
        return jsonify({"mensagem": "Venda gravada com sucesso!"}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao salvar venda: {e}")
        return jsonify({"erro": str(e)}), 500

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)