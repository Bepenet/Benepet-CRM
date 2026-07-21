import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Usuario, Cliente, Venda, ItemVenda

app = Flask(__name__)

# Configurações básicas de Segurança
app.config['SECRET_KEY'] = 'benepet_crm_secret_key_123'

# 1️⃣ CONFIGURAÇÃO DA CONEXÃO DO BANCO DE DADOS
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

# Variável de controle para rodar a criação de tabelas uma única vez
_tabelas_verificadas = False

# 2️⃣ HOOK DE INICIALIZAÇÃO SEGURO COM CRIPTOGRAFIA
@app.before_request
def inicializar_banco_seguro():
    global _tabelas_verificadas
    if not _tabelas_verificadas:
        try:
            db.create_all()
            # Gera a conta padrão criptografada caso a tabela esteja limpa
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

# --- ROTAS DO FLASK ---

@app.route('/')
def index():
    if usuario_esta_logado():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/criar_admin_forcado')
def criar_admin_forcado():
    try:
        # Derruba as tabelas antigas com o limite curto e recria com db.String(256)
        db.drop_all() 
        db.create_all()
            
        senha_criptografada = generate_password_hash('admin')
        usuario_padrao = Usuario(login='admin', senha=senha_criptografada)
        db.session.add(usuario_padrao)
        db.session.commit()
        return "Tabelas atualizadas e Usuário 'admin' gerado com SENHA CRIPTOGRAFADA no PostgreSQL!"
    except Exception as e:
        return f"Falha ao forçar a gravação inicial: {str(e)}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')
        
        try:
            user = Usuario.query.filter_by(login=usuario).first()
            # Compara o hash seguro do banco com a senha digitada
            if user and check_password_hash(user.senha, senha):
                session['usuario'] = user.login
                return redirect(url_for('dashboard'))
            else:
                flash('Usuário ou senha inválidos!', 'erro')
        except Exception as e:
            flash('Conexão instável com a base de dados. Tente novamente.', 'erro')
            print(f"Erro de login: {e}")
            
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
            # Criptografa a senha antes de salvar um novo usuário no sistema
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