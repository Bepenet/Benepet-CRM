import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from models import db, Usuario, Cliente, Venda, ItemVenda

app = Flask(__name__)

# Configurações básicas do Banco de Dados e Segurança
app.config['SECRET_KEY'] = 'benepet_crm_secret_key_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///petcrm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializa o banco de dados no Flask
db.init_app(app)

# Cria as tabelas automaticamente se elas não existirem
with app.app_context():
    db.create_all()

# --- ROTAS DO SISTEMA ---

@app.route('/')
def index():
    # Tela inicial redireciona para o login ou dashboard
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')
        
        # Procura o utilizador no banco de dados
        user = Usuario.query.filter_by(login=usuario, senha=senha).first()
        if user:
            # O redirect envia o navegador para o dashboard usando o método GET correto
            return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha inválidos!', 'erro')
            
    return render_template('login.html')

@app.route('/dashboard', methods=['GET'])
def dashboard():
    # Puxa informações para os blocos de resumo do CRM
    clientes_total = Cliente.query.count()
    vendas_total = Venda.query.count()
    
    # Lista de clientes cadastrados para exibição rápida
    clientes = Cliente.query.all()
    
    return render_template('dashboard.html', 
                           clientes_total=clientes_total, 
                           vendas_total=vendas_total, 
                           clientes=clientes)

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
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
    # Rota que carrega a nova tela de vendas/carrinho
    clientes = Cliente.query.all()
    # Puxa o histórico de vendas ordenando pelas mais recentes
    historico_vendas = Venda.query.order_by(Venda.data.desc()).all()
    return render_template('vendas.html', clientes=clientes, vendas=historico_vendas)

@app.route('/salvar_venda_multipla', methods=['POST'])
def salvar_venda_multipla():
    dados = request.get_json()
    
    if not dados:
        return jsonify({"erro": "Dados inválidos"}), 400
        
    cliente_id = dados.get('cliente_id')
    data_str = dados.get('data')
    valor_total = dados.get('valor_total')
    itens = dados.get('itens')
    
    # Trata a data enviada pela tela
    data_venda = datetime.strptime(data_str, '%Y-%m-%d') if data_str else datetime.utcnow()
    
    try:
        # 1. Registra o cabeçalho da Venda
        nova_venda = Venda(
            cliente_id=cliente_id,
            data=data_venda,
            valor_total=valor_total
        )
        db.session.add(nova_venda)
        db.session.flush() # Gera o ID da venda temporariamente
        
        # 2. Registra cada item do carrinho associado a esta venda
        for item in itens:
            novo_item = ItemVenda(
                venda_id=nova_venda.id,
                produto=item['produto'],
                quantidade=int(item['quantidade']),
                valor_unitario=float(item['valor_unitario']),
                valor_subtotal=float(item['valor_subtotal'])
            )
            db.session.add(novo_item)
            
        # 3. Confirma a gravação de tudo no banco
        db.session.commit()
        return jsonify({"mensagem": "Venda gravada com sucesso!"}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao salvar venda: {e}")
        return jsonify({"erro": str(e)}), 500

# --- INICIALIZAÇÃO DO SERVIDOR ---

if __name__ == "__main__":
    # Configuração dinâmica para rodar localmente (porta 5000) ou no Render (variável PORT)
    porta = int(os.environ.get("PORT", 5000))
    # host="0.0.0.0" permite que o Render encontre e publique o sistema na internet
    app.run(host="0.0.0.0", port=porta)