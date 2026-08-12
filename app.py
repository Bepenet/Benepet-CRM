import os
import secrets
import unicodedata
from pathlib import Path
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from datetime import datetime, timedelta
from sqlalchemy import inspect, text, func
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_migrate import Migrate
from models import db, Usuario, Cliente, Venda, ItemVenda, Prospeccao, HistoricoProspeccao, Vendedor, agora_brasil
import backup as backup_mod

app = Flask(__name__)


def _carregar_secret_key():
    """Chave de sessão: vem da variável de ambiente (SECRET_KEY) ou, como plano
    B, de um arquivo persistente local gerado na primeira execução."""
    chave = os.environ.get('SECRET_KEY')
    if chave:
        return chave
    caminho = Path(app.instance_path) / 'secret_key'
    try:
        return caminho.read_text(encoding='utf-8').strip()
    except OSError:
        nova = secrets.token_hex(32)
        try:
            Path(app.instance_path).mkdir(parents=True, exist_ok=True)
            caminho.write_text(nova, encoding='utf-8')
        except OSError:
            pass
        return nova


app.config['SECRET_KEY'] = _carregar_secret_key()
csrf = CSRFProtect(app)

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

@app.template_filter('moeda')
def filtro_moeda(valor):
    return formatar_moeda(valor)

def parametros_periodo():
    """Lê os filtros de período (Mês, Ano ou intervalo) e devolve o intervalo de
    datas (data_inicio/data_fim) e o rótulo para exibição nos relatórios."""
    hoje = agora_brasil()
    meses_nomes = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                   'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

    periodo = request.args.get('periodo', 'mes')
    mes = request.args.get('mes', hoje.month, type=int)
    ano = request.args.get('ano', hoje.year, type=int)
    data_inicio_str = request.args.get('data_inicio', '')
    data_fim_str = request.args.get('data_fim', '')

    if periodo == 'ano':
        data_inicio = datetime(ano, 1, 1)
        data_fim = datetime(ano, 12, 31, 23, 59, 59)
        rotulo_periodo = str(ano)
    elif periodo == 'periodo':
        if not data_inicio_str:
            data_inicio_str = datetime(hoje.year, hoje.month, 1).strftime('%Y-%m-%d')
        if not data_fim_str:
            data_fim_str = hoje.strftime('%Y-%m-%d')
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        rotulo_periodo = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
    else:
        data_inicio = datetime(ano, mes, 1)
        if mes == 12:
            data_fim = datetime(ano + 1, 1, 1) - timedelta(seconds=1)
        else:
            data_fim = datetime(ano, mes + 1, 1) - timedelta(seconds=1)
        rotulo_periodo = f"{meses_nomes[mes - 1]} de {ano}"

    return {
        'periodo': periodo,
        'mes': mes,
        'ano': ano,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'data_inicio_str': data_inicio_str,
        'data_fim_str': data_fim_str,
        'rotulo_periodo': rotulo_periodo,
        'hoje': hoje,
        'meses_nomes': meses_nomes,
    }

# Número que recebe o aviso de vendas confirmadas para emissão de NF (com DDI+DDD)
WHATSAPP_NF_NUMERO = os.environ.get('WHATSAPP_NF_NUMERO', '5547988139107')

def montar_link_whatsapp_nf(venda, convertida_de_consignacao=False):
    """Monta o link do WhatsApp (wa.me) com os dados da venda prontos para gerar a NF."""
    cliente = venda.cliente
    if venda.emitir_nf is False:
        linhas = [
            "📄 *Nova venda confirmada*",
            "🚫 *Não Emitir NF*",
        ]
    else:
        linhas = [
            "📄 *Nova venda confirmada - gerar NF*",
        ]
    if convertida_de_consignacao:
        linhas.append("✅ *Venda convertida de Consignado para Venda Confirmada*")
    linhas.append(f"Cliente (Razão Social): {cliente.nome}")
    if cliente.nome_fantasia:
        linhas.append(f"Nome Fantasia: {cliente.nome_fantasia}")
    linhas.append(f"CNPJ/CPF: {cliente.cpf_cnpj or 'não informado'}")
    if cliente.endereco:
        linhas.append(f"Endereço: {cliente.endereco}")
    if cliente.cidade:
        linhas.append(f"Cidade/UF: {cliente.cidade}/{cliente.uf}" if cliente.uf else f"Cidade/UF: {cliente.cidade}")
    if cliente.cep:
        linhas.append(f"CEP: {cliente.cep}")
    if cliente.email:
        linhas.append(f"E-mail: {cliente.email}")
    linhas.append(f"Data: {venda.data_efetiva.strftime('%d/%m/%Y')}")
    linhas.append(f"Prazo de Pagamento: {venda.prazo_pagamento or 'não informado'}")
    linhas.append("")
    linhas.append("Itens:")
    for item in venda.itens:
        linhas.append(f"- {item.produto} x{item.quantidade} un x R$ {formatar_moeda(item.valor_unitario)} = R$ {formatar_moeda(item.valor_subtotal)}")
    linhas.append("")
    linhas.append(f"*Total: R$ {formatar_moeda(venda.valor_total)}*")

    mensagem = "\n".join(linhas)
    return f"https://wa.me/{WHATSAPP_NF_NUMERO}?text={quote(mensagem)}"


def validar_e_normalizar_itens(itens):
    """Valida os itens recebidos do cliente e devolve (lista_normalizada, total).

    O valor total e os subtotais são sempre recalculados aqui, no servidor,
    para nunca confiar no que foi enviado pelo navegador. Em caso de erro,
    devolve (None, mensagem_de_erro)."""
    if not itens:
        return None, "A venda precisa ter pelo menos um item."

    itens_limpos = []
    valor_total = 0.0
    for item in itens:
        produto = (item.get('produto') or '').strip()
        try:
            quantidade = int(item['quantidade'])
            valor_unitario = float(item['valor_unitario'])
        except (KeyError, TypeError, ValueError):
            return None, "Item inválido: confira produto, quantidade e valor."
        if not produto or quantidade <= 0 or valor_unitario < 0:
            return None, "Quantidade precisa ser maior que zero e o produto precisa de nome."
        subtotal = round(quantidade * valor_unitario, 2)
        valor_total += subtotal
        itens_limpos.append({
            'produto': produto,
            'quantidade': quantidade,
            'valor_unitario': valor_unitario,
            'valor_subtotal': subtotal,
        })

    return itens_limpos, round(valor_total, 2)

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
migrate = Migrate(app, db)

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
        if 'vendedor' not in colunas_venda:
            conn.execute(text('ALTER TABLE venda ADD COLUMN vendedor VARCHAR(100)'))
            conn.commit()
        if 'paga' not in colunas_venda:
            conn.execute(text('ALTER TABLE venda ADD COLUMN paga BOOLEAN DEFAULT FALSE'))
            conn.commit()
        if 'data_pagamento' not in colunas_venda:
            conn.execute(text('ALTER TABLE venda ADD COLUMN data_pagamento TIMESTAMP'))
            conn.commit()
        if 'emitir_nf' not in colunas_venda:
            conn.execute(text('ALTER TABLE venda ADD COLUMN emitir_nf BOOLEAN DEFAULT TRUE'))
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
        if 'email' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN email VARCHAR(120)'))
            conn.commit()
        if 'cidade' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN cidade VARCHAR(100)'))
            conn.commit()
        if 'cep' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN cep VARCHAR(10)'))
            conn.commit()
        if 'uf' not in colunas_cliente:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN uf VARCHAR(2)'))
            conn.commit()

    colunas_usuario = [c['name'] for c in inspector.get_columns('usuario')]
    with db.engine.connect() as conn:
        if 'precisa_trocar_senha' not in colunas_usuario:
            conn.execute(text('ALTER TABLE usuario ADD COLUMN precisa_trocar_senha BOOLEAN DEFAULT TRUE'))
            conn.commit()
        if 'admin' not in colunas_usuario:
            conn.execute(text('ALTER TABLE usuario ADD COLUMN admin BOOLEAN DEFAULT FALSE'))
            conn.commit()

    with db.engine.connect() as conn:
        if 'vendedor_id' not in [c['name'] for c in inspector.get_columns('cliente')]:
            conn.execute(text('ALTER TABLE cliente ADD COLUMN vendedor_id INTEGER'))
            conn.commit()
        if 'vendedor_id' not in [c['name'] for c in inspector.get_columns('venda')]:
            conn.execute(text('ALTER TABLE venda ADD COLUMN vendedor_id INTEGER'))
            conn.commit()

    colunas_prospeccao = [c['name'] for c in inspector.get_columns('prospeccao')]
    with db.engine.connect() as conn:
        if 'proxima_acao_hora' not in colunas_prospeccao:
            conn.execute(text('ALTER TABLE prospeccao ADD COLUMN proxima_acao_hora VARCHAR(5)'))
            conn.commit()

    try:
        colunas_vendedor = [c['name'] for c in inspector.get_columns('vendedor')]
        with db.engine.connect() as conn:
            if 'email' not in colunas_vendedor:
                conn.execute(text('ALTER TABLE vendedor ADD COLUMN email VARCHAR(120)'))
                conn.commit()
            if 'endereco' not in colunas_vendedor:
                conn.execute(text('ALTER TABLE vendedor ADD COLUMN endereco VARCHAR(255)'))
                conn.commit()
            if 'cidade' not in colunas_vendedor:
                conn.execute(text('ALTER TABLE vendedor ADD COLUMN cidade VARCHAR(100)'))
                conn.commit()
            if 'cep' not in colunas_vendedor:
                conn.execute(text('ALTER TABLE vendedor ADD COLUMN cep VARCHAR(10)'))
                conn.commit()
            if 'uf' not in colunas_vendedor:
                conn.execute(text('ALTER TABLE vendedor ADD COLUMN uf VARCHAR(2)'))
                conn.commit()
    except Exception as e:
        print(f"Aviso ao verificar tabela vendedor: {e}")


def vincular_vendedores_existentes():
    """Backfill pontual: preenche vendedor_id de Cliente/Venda antigos a partir
    do nome gravado na coluna de texto, quando houver um cadastro correspondente."""
    for c in Cliente.query.filter(Cliente.vendedor.isnot(None), Cliente.vendedor != '',
                                  Cliente.vendedor_id.is_(None)).all():
        vend = Vendedor.query.filter_by(nome=c.vendedor).first()
        if vend:
            c.vendedor_id = vend.id
    for v in Venda.query.filter(Venda.vendedor.isnot(None), Venda.vendedor != '',
                                Venda.vendedor_id.is_(None)).all():
        vend = Vendedor.query.filter_by(nome=v.vendedor).first()
        if vend:
            v.vendedor_id = vend.id
    db.session.commit()


def aplicar_vendedor_por_nome(registro, nome):
    """Mantém a coluna de texto e a FK de vendedor em sincronia num Cliente/Venda."""
    registro.vendedor = nome or None
    registro.vendedor_id = None
    if nome:
        vend = Vendedor.query.filter_by(nome=nome).first()
        if vend:
            registro.vendedor_id = vend.id


@app.before_request
def inicializar_banco_seguro():
    global _tabelas_verificadas
    if not _tabelas_verificadas:
        try:
            db.create_all()
            garantir_colunas_novas()
            vincular_vendedores_existentes()
            admin_login = Usuario.query.filter_by(login='admin').first()
            if admin_login:
                if not admin_login.admin:
                    admin_login.admin = True
                    db.session.commit()
            elif not Usuario.query.first():
                senha_criptografada = generate_password_hash('admin')
                usuario_padrao = Usuario(login='admin', senha=senha_criptografada,
                                         precisa_trocar_senha=True, admin=True)
                db.session.add(usuario_padrao)
                db.session.commit()
            else:
                primeiro = Usuario.query.order_by(Usuario.id).first()
                if primeiro and not primeiro.admin:
                    primeiro.admin = True
                    db.session.commit()
            _tabelas_verificadas = True
        except Exception as e:
            print(f"Aviso de verificação do banco em produção: {e}")

def usuario_esta_logado():
    return 'usuario' in session

def usuario_atual():
    """Devolve o usuário logado (ou None)."""
    if 'usuario' not in session:
        return None
    return Usuario.query.filter_by(login=session['usuario']).first()

def is_admin():
    """True se o usuário logado tem papel de administrador."""
    user = usuario_atual()
    return bool(user and user.admin)

@app.context_processor
def injetar_contexto_global():
    return {'is_admin': is_admin()}

@app.errorhandler(CSRFError)
def tratar_erro_csrf(e):
    """Falha de token CSRF (formulário/sessão expirado ou ataque)."""
    if request.is_json:
        return jsonify({"erro": "Sessão expirada. Recarregue a página e tente novamente."}), 400
    flash('Sessão expirada ou token de segurança inválido. Tente novamente.', 'erro')
    destino = url_for('dashboard') if usuario_esta_logado() else url_for('login')
    return redirect(destino), 400

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

    tipos_validos = {
        'historico_vendas': 'Histórico de Vendas',
        'vendas_por_vendedor': 'Vendas por Vendedor',
        'vendas_por_cliente': 'Vendas por Cliente',
        'vendas_por_mes': 'Vendas por Mês',
        'comissao': 'Comissão de Vendedores',
        'historico_matriz': 'Histórico de Vendas (Matriz)',
        'proximo_contato': 'Próximo Contato',
    }
    tipo = request.args.get('relatorio', 'historico_vendas')
    if tipo not in tipos_validos:
        tipo = 'historico_vendas'

    vendedor_filtro = request.args.get('vendedor', '')
    cliente_id = request.args.get('cliente_id', type=int)

    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()

    pp = parametros_periodo()
    contexto = {
        'tipo': tipo,
        'tipos_validos': tipos_validos,
        'vendedor_filtro': vendedor_filtro,
        'vendedores': vendedores,
        'clientes': clientes,
        'cliente_id': cliente_id,
        'cliente_selecionado': Cliente.query.get(cliente_id) if cliente_id else None,
    }
    contexto.update(pp)

    data_efetiva = func.coalesce(Venda.data_confirmacao, Venda.data)

    if tipo == 'proximo_contato':
        todos_clientes = Cliente.query.all()
        contexto['clientes_contato'] = sorted(todos_clientes, key=lambda c: c.proximo_contato)
        return render_template('relatorios.html', **contexto)

    if tipo == 'historico_vendas':
        pagina = request.args.get('pagina', 1, type=int)
        consulta = Venda.query.filter(data_efetiva.between(pp['data_inicio'], pp['data_fim']))
        if vendedor_filtro:
            consulta = consulta.filter(Venda.vendedor == vendedor_filtro)
        consulta = consulta.order_by(Venda.data.desc())
        contexto['paginacao'] = consulta.paginate(page=pagina, per_page=25, error_out=False)

    elif tipo == 'vendas_por_vendedor':
        vendedor_expr = func.coalesce(func.nullif(Venda.vendedor, ''),
                                      func.nullif(Cliente.vendedor, ''),
                                      'Sem vendedor definido')
        consulta = db.session.query(
            vendedor_expr.label('vendedor'),
            func.count().label('quantidade_vendas'),
            func.sum(Venda.valor_total).label('valor'),
        ).select_from(Venda).join(Cliente, Venda.cliente_id == Cliente.id)\
            .filter(Venda.status == 'Confirmada')\
            .filter(data_efetiva.between(pp['data_inicio'], pp['data_fim']))
        if vendedor_filtro:
            consulta = consulta.filter(vendedor_expr == vendedor_filtro)
        linhas = consulta.group_by(vendedor_expr)\
            .order_by(func.sum(Venda.valor_total).desc()).all()

        totais = {}
        for linha in linhas:
            totais[linha.vendedor] = {
                'quantidade_vendas': linha.quantidade_vendas,
                'valor': linha.valor or 0,
            }
        for dados in totais.values():
            dados['valor_fmt'] = formatar_moeda(dados['valor'])
        contexto['vendedores_resumo'] = sorted(totais.items(),
                                               key=lambda item: item[1]['valor'], reverse=True)

    elif tipo == 'vendas_por_cliente':
        cliente = contexto['cliente_selecionado']
        contexto['vendas_cliente'] = []
        contexto['total_vendas'] = 0
        contexto['valor_total_fmt'] = formatar_moeda(0)
        if cliente:
            consulta = Venda.query.filter(Venda.cliente_id == cliente.id)\
                .filter(data_efetiva.between(pp['data_inicio'], pp['data_fim']))
            if vendedor_filtro:
                consulta = consulta.filter(Venda.vendedor == vendedor_filtro)
            vendas = consulta.order_by(Venda.data.desc()).all()
            contexto['vendas_cliente'] = vendas
            contexto['total_vendas'] = len(vendas)
            contexto['valor_total_fmt'] = formatar_moeda(sum(v.valor_total for v in vendas))

    elif tipo == 'vendas_por_mes':
        meses_pt = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
        ano_expr = func.extract('year', data_efetiva)
        mes_expr = func.extract('month', data_efetiva)
        consulta = db.session.query(
            ano_expr.label('ano'),
            mes_expr.label('mes'),
            func.count().label('quantidade_vendas'),
            func.sum(Venda.valor_total).label('valor'),
        ).filter(Venda.status == 'Confirmada')\
            .filter(data_efetiva.between(pp['data_inicio'], pp['data_fim']))
        if vendedor_filtro:
            consulta = consulta.filter(Venda.vendedor == vendedor_filtro)
        linhas = consulta.group_by(ano_expr, mes_expr)\
            .order_by(ano_expr.desc(), mes_expr.desc()).all()

        totais = {}
        for linha in linhas:
            chave = (int(linha.ano), int(linha.mes))
            totais[chave] = {'quantidade_vendas': linha.quantidade_vendas, 'valor': linha.valor or 0}
        for chave, dados in totais.items():
            dados['valor_fmt'] = formatar_moeda(dados['valor'])
            dados['label'] = f"{meses_pt[chave[1]]}/{chave[0]}"
        contexto['meses_resumo'] = sorted(totais.items(), key=lambda item: item[0], reverse=True)

    elif tipo == 'comissao':
        consulta = Venda.query.filter(
            Venda.paga.is_(True),
            Venda.data_pagamento.isnot(None),
            Venda.data_pagamento.between(pp['data_inicio'], pp['data_fim']),
        )
        if vendedor_filtro:
            consulta = consulta.filter(Venda.vendedor == vendedor_filtro)
        vendas_pagas = consulta.order_by(Venda.data_pagamento.desc()).all()

        pct_por_vendedor = {v.nome: v.comissao_pct for v in Vendedor.query.all()}
        resumo = {}
        for venda in vendas_pagas:
            nome_vendedor = venda.vendedor or 'Sem vendedor'
            pct = pct_por_vendedor.get(venda.vendedor, 0) if venda.vendedor else 0
            venda.comissao_valor = round(venda.valor_total * pct / 100, 2) if pct else 0.0
            if nome_vendedor not in resumo:
                resumo[nome_vendedor] = {'qtd': 0, 'total': 0.0, 'pct': pct}
            resumo[nome_vendedor]['qtd'] += 1
            resumo[nome_vendedor]['total'] += venda.valor_total
            resumo[nome_vendedor]['comissao'] = resumo[nome_vendedor].get('comissao', 0.0) + venda.comissao_valor
        for dados in resumo.values():
            dados['total_fmt'] = formatar_moeda(dados['total'])
            dados['comissao_fmt'] = formatar_moeda(dados['comissao'])
        contexto['resumo_comissao'] = resumo
        contexto['vendas_pagas'] = vendas_pagas

    elif tipo == 'historico_matriz':
        ano = pp['ano']
        vendedor_expr = func.coalesce(func.nullif(Venda.vendedor, ''),
                                      func.nullif(Cliente.vendedor, ''),
                                      'Sem vendedor')
        cliente_expr = func.coalesce(func.nullif(Cliente.nome_fantasia, ''), Cliente.nome)
        consulta = db.session.query(
            vendedor_expr.label('vendedor'),
            cliente_expr.label('cliente'),
            func.extract('month', data_efetiva).label('mes'),
            func.sum(Venda.valor_total).label('valor'),
        ).select_from(Venda).join(Cliente, Venda.cliente_id == Cliente.id)\
            .filter(Venda.status == 'Confirmada')\
            .filter(func.extract('year', data_efetiva) == ano)
        if vendedor_filtro:
            consulta = consulta.filter(vendedor_expr == vendedor_filtro)
        linhas = consulta.group_by(vendedor_expr, cliente_expr, func.extract('month', data_efetiva)).all()

        agrupado = {}
        totais_meses = [0.0] * 12
        total_geral = 0.0
        for linha in linhas:
            vendedor = linha.vendedor
            cliente = linha.cliente
            mes = int(linha.mes)
            valor = linha.valor or 0
            grupo = agrupado.setdefault(vendedor, {'clientes': {}, 'total': 0.0})
            grupo['total'] += valor
            dados_cliente = grupo['clientes'].setdefault(cliente, {'meses': [0.0] * 12, 'total': 0.0})
            dados_cliente['meses'][mes - 1] += valor
            dados_cliente['total'] += valor
            totais_meses[mes - 1] += valor
            total_geral += valor

        lista = []
        for vendedor, grupo in agrupado.items():
            clientes_g = sorted(grupo['clientes'].items(), key=lambda item: item[1]['total'], reverse=True)
            lista.append({'vendedor': vendedor, 'total': grupo['total'], 'clientes': clientes_g})
        lista.sort(key=lambda g: g['total'], reverse=True)

        contexto['grupos_matriz'] = lista
        contexto['totais_meses'] = totais_meses
        contexto['total_geral'] = total_geral

    return render_template('relatorios.html', **contexto)

@app.route('/relatorios/proximo-contato')
def relatorio_proximo_contato():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    return redirect(url_for('relatorios', relatorio='proximo_contato'))

@app.route('/relatorios/vendas-por-vendedor')
def relatorio_vendas_por_vendedor():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    return redirect(url_for('relatorios', relatorio='vendas_por_vendedor'))

@app.route('/relatorios/vendas-por-cliente')
def relatorio_vendas_por_cliente():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    return redirect(url_for('relatorios', relatorio='vendas_por_cliente'))

@app.route('/relatorios/vendas-por-mes')
def relatorio_vendas_por_mes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    return redirect(url_for('relatorios', relatorio='vendas_por_mes'))

@app.route('/relatorios/historico-vendas')
def relatorio_historico_vendas():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    return redirect(url_for('relatorios', relatorio='historico_matriz'))

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
        venda.data_confirmacao = agora_brasil()
        db.session.commit()
        flash(f'Consignação #{venda.id} confirmada como venda!', 'sucesso')
        flash(montar_link_whatsapp_nf(venda, convertida_de_consignacao=True), 'whatsapp_link')
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
    cliente.contato_adiado_ate = agora_brasil() + timedelta(days=dias)
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

@app.route('/vendedores', methods=['GET', 'POST'])
def vendedores():
    if not is_admin():
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        endereco = request.form.get('endereco')
        cep = request.form.get('cep')
        cidade = request.form.get('cidade')
        uf = request.form.get('uf')
        comissao_pct = request.form.get('comissao_pct') or 0

        if not nome:
            flash('Informe o nome do vendedor.', 'erro')
        elif Vendedor.query.filter_by(nome=nome).first():
            flash('Já existe um vendedor com esse nome.', 'erro')
        else:
            db.session.add(Vendedor(nome=nome, telefone=telefone, email=email, endereco=endereco, cep=cep, cidade=cidade, uf=uf, comissao_pct=float(comissao_pct)))
            db.session.commit()
            flash(f'Vendedor "{nome}" cadastrado com sucesso!', 'sucesso')
        return redirect(url_for('vendedores'))

    lista = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template('vendedores.html', vendedores=lista)

@app.route('/vendedores/<int:id>/editar', methods=['POST'])
def editar_vendedor(id):
    if not is_admin():
        return redirect(url_for('login'))

    vendedor = Vendedor.query.get_or_404(id)
    nome_antigo = vendedor.nome
    nome_novo = (request.form.get('nome') or '').strip()

    if not nome_novo:
        flash('Informe o nome do vendedor.', 'erro')
        return redirect(url_for('vendedores'))

    duplicado = Vendedor.query.filter(Vendedor.nome == nome_novo, Vendedor.id != id).first()
    if duplicado:
        flash('Já existe outro vendedor com esse nome.', 'erro')
        return redirect(url_for('vendedores'))

    vendedor.nome = nome_novo
    vendedor.telefone = request.form.get('telefone')
    vendedor.email = request.form.get('email')
    vendedor.endereco = request.form.get('endereco')
    vendedor.cep = request.form.get('cep')
    vendedor.cidade = request.form.get('cidade')
    vendedor.uf = request.form.get('uf')
    vendedor.comissao_pct = float(request.form.get('comissao_pct') or 0)
    db.session.commit()

    if nome_antigo != nome_novo:
        for cliente in Cliente.query.filter_by(vendedor=nome_antigo).all():
            cliente.vendedor = nome_novo
        for venda in Venda.query.filter_by(vendedor=nome_antigo).all():
            venda.vendedor = nome_novo
        db.session.commit()

    flash(f'Vendedor "{nome_novo}" atualizado!', 'sucesso')
    return redirect(url_for('vendedores'))

@app.route('/vendedores/<int:id>/excluir', methods=['POST'])
def excluir_vendedor(id):
    if not is_admin():
        return redirect(url_for('login'))

    vendedor = Vendedor.query.get_or_404(id)
    nome = vendedor.nome
    db.session.delete(vendedor)
    for cliente in Cliente.query.filter_by(vendedor=nome).all():
        cliente.vendedor = None
        cliente.vendedor_id = None
    for venda in Venda.query.filter_by(vendedor=nome).all():
        venda.vendedor = None
        venda.vendedor_id = None
    db.session.commit()
    flash(f'Vendedor "{nome}" excluído.', 'sucesso')
    return redirect(url_for('vendedores'))

@app.route('/clientes', methods=['GET', 'POST'])
def clientes():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome = request.form.get('nome')
        nome_fantasia = request.form.get('nome_fantasia')
        cpf_cnpj = request.form.get('cpf_cnpj')
        endereco = request.form.get('endereco')
        cep = request.form.get('cep')
        cidade = request.form.get('cidade')
        uf = request.form.get('uf')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        contato = request.form.get('contato')
        vendedor = request.form.get('vendedor')
        dias_aviso = int(request.form.get('dias_aviso', 30))
        data_cadastro_str = request.form.get('data_cadastro')

        if data_cadastro_str:
            data_cadastro = datetime.strptime(data_cadastro_str, '%Y-%m-%d')
        else:
            data_cadastro = agora_brasil()

        novo_cliente = Cliente(
            nome=nome,
            nome_fantasia=nome_fantasia,
            cpf_cnpj=cpf_cnpj,
            endereco=endereco,
            cep=cep,
            cidade=cidade,
            uf=uf,
            telefone=telefone,
            email=email,
            contato=contato,
            data_cadastro=data_cadastro,
            dias_aviso=dias_aviso,
            periodo_retorno=dias_aviso
        )
        aplicar_vendedor_por_nome(novo_cliente, vendedor)
        db.session.add(novo_cliente)
        db.session.commit()
        flash('Cliente cadastrado com sucesso!', 'sucesso')
        return redirect(url_for('clientes'))

    todos_clientes = Cliente.query.all()
    hoje_formatado = agora_brasil().strftime('%Y-%m-%d')
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template('clientes.html', clientes=todos_clientes, hoje=hoje_formatado, vendedores=vendedores)

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
        cliente.cep = request.form.get('cep')
        cliente.cidade = request.form.get('cidade')
        cliente.uf = request.form.get('uf')
        cliente.telefone = request.form.get('telefone')
        cliente.email = request.form.get('email')
        cliente.contato = request.form.get('contato')
        aplicar_vendedor_por_nome(cliente, request.form.get('vendedor'))
        dias_aviso = int(request.form.get('dias_aviso', 30))
        cliente.dias_aviso = dias_aviso
        cliente.periodo_retorno = dias_aviso

        db.session.commit()
        flash('Dados do cliente atualizados com sucesso!', 'sucesso')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    historico_vendas = sorted(cliente.vendas, key=lambda v: v.data, reverse=True)
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template('cliente_detalhe.html', cliente=cliente, vendas=historico_vendas, vendedores=vendedores)

@app.route('/vendas')
def vendas():
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    clientes = sorted(Cliente.query.all(), key=lambda c: c.nome_exibicao or c.nome)
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    historico_vendas = Venda.query.order_by(Venda.data.desc()).all()
    return render_template('vendas.html', clientes=clientes, vendas=historico_vendas, vendedores=vendedores)

@app.route('/usuarios', methods=['GET', 'POST'])
def usuarios():
    if not is_admin():
        flash('Acesso restrito apenas para o administrador!', 'erro')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        novo_login = request.form.get('usuario')
        nova_senha = request.form.get('senha')
        eh_admin = bool(request.form.get('admin'))

        if not novo_login or not nova_senha:
            flash('Informe login e senha.', 'erro')
        elif Usuario.query.filter_by(login=novo_login).first():
            flash('Esse nome de usuário já existe!', 'erro')
        else:
            senha_segura = generate_password_hash(nova_senha)
            novo_user = Usuario(login=novo_login, senha=senha_segura,
                                precisa_trocar_senha=True, admin=eh_admin)
            db.session.add(novo_user)
            db.session.commit()
            flash('Usuário criado com sucesso!', 'sucesso')
        return redirect(url_for('usuarios'))

    lista_usuarios = Usuario.query.all()
    return render_template('usuarios.html', usuarios=lista_usuarios, usuario_atual_login=session['usuario'])

@app.route('/usuarios/<int:id>/admin', methods=['POST'])
def alternar_admin_usuario(id):
    if not is_admin():
        flash('Acesso restrito apenas para o administrador!', 'erro')
        return redirect(url_for('dashboard'))

    alvo = Usuario.query.get_or_404(id)
    if alvo.login == session['usuario']:
        flash('Você não pode remover o próprio acesso de administrador.', 'erro')
        return redirect(url_for('usuarios'))

    alvo.admin = not alvo.admin
    db.session.commit()
    flash(f'Papel de {alvo.login} atualizado.', 'sucesso')
    return redirect(url_for('usuarios'))

@app.route('/salvar_venda_multipla', methods=['POST'])
def salvar_venda_multipla():
    if not usuario_esta_logado():
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.get_json()
    cliente_id = dados.get('cliente_id')
    data_str = dados.get('data')
    itens = dados.get('itens')
    prazo_pagamento = dados.get('prazo_pagamento')
    tipo_venda = dados.get('tipo_venda', 'Normal')
    vendedor = dados.get('vendedor')
    emitir_nf = dados.get('emitir_nf', True)

    data_venda = datetime.strptime(data_str, '%Y-%m-%d') if data_str else agora_brasil()
    status_venda = 'Pendente' if tipo_venda == 'Consignado' else 'Confirmada'

    itens_limpos, valor_total = validar_e_normalizar_itens(itens)
    if itens_limpos is None:
        return jsonify({"erro": valor_total}), 400

    try:
        nova_venda = Venda(
            cliente_id=cliente_id,
            data=data_venda,
            valor_total=valor_total,
            prazo_pagamento=prazo_pagamento,
            tipo=tipo_venda,
            status=status_venda,
            vendedor=vendedor,
            emitir_nf=bool(emitir_nf)
        )
        aplicar_vendedor_por_nome(nova_venda, vendedor)
        db.session.add(nova_venda)
        db.session.flush()

        for item in itens_limpos:
            novo_item = ItemVenda(
                venda_id=nova_venda.id,
                produto=item['produto'],
                quantidade=item['quantidade'],
                valor_unitario=item['valor_unitario'],
                valor_subtotal=item['valor_subtotal']
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
    args = request.args.to_dict()
    args['relatorio'] = 'historico_vendas'
    return redirect(url_for('relatorios', **args))

@app.route('/venda/detalhar/<int:id>')
def detalhar_venda(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda = Venda.query.get(id)
    if not venda:
        return "Venda não encontrada", 404

    itens = venda.itens
    return render_template('detalhe_vendas.html', venda=venda, itens=itens, modo_visualizacao=True,
                           hoje=agora_brasil())

@app.route('/vendas/<int:id>/duplicar')
def duplicar_venda(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda_origem = Venda.query.get_or_404(id)
    clientes = Cliente.query.all()
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()

    dados = {
        'cliente_id': venda_origem.cliente_id,
        'prazo_pagamento': venda_origem.prazo_pagamento,
        'vendedor': venda_origem.vendedor or '',
        'tipo_venda': venda_origem.tipo or 'Normal',
        'emitir_nf': venda_origem.emitir_nf is not False,
        'itens': [
            {
                'produto': item.produto,
                'quantidade': item.quantidade,
                'valor_unitario': item.valor_unitario,
                'valor_subtotal': item.valor_subtotal,
            }
            for item in venda_origem.itens
        ],
    }
    return render_template('vendas.html', clientes=clientes, vendas=[],
                           vendedores=vendedores, duplicar_dados=dados,
                           venda_origem_id=venda_origem.id)

@app.route('/vendas/<int:id>/editar', methods=['GET', 'POST'])
def editar_venda(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda = Venda.query.get_or_404(id)

    if request.method == 'POST':
        dados = request.get_json()
        cliente_id = dados.get('cliente_id')
        data_str = dados.get('data')
        prazo_pagamento = dados.get('prazo_pagamento')
        tipo_venda = dados.get('tipo_venda', 'Normal')
        status = dados.get('status', 'Confirmada')
        vendedor = dados.get('vendedor')
        itens = dados.get('itens')
        emitir_nf = dados.get('emitir_nf', venda.emitir_nf)

        itens_limpos, valor_total = validar_e_normalizar_itens(itens)
        if itens_limpos is None:
            return jsonify({"erro": valor_total}), 400

        data_venda = datetime.strptime(data_str, '%Y-%m-%d') if data_str else venda.data

        venda.cliente_id = cliente_id
        venda.data = data_venda
        venda.prazo_pagamento = prazo_pagamento
        venda.tipo = tipo_venda
        venda.status = status
        venda.emitir_nf = bool(emitir_nf)
        venda.valor_total = valor_total
        aplicar_vendedor_por_nome(venda, vendedor)

        if status == 'Confirmada':
            if not venda.data_confirmacao:
                venda.data_confirmacao = venda.data
        else:
            venda.data_confirmacao = None

        for item in list(venda.itens):
            db.session.delete(item)
        db.session.flush()

        for item in itens:
            db.session.add(ItemVenda(
                venda_id=venda.id,
                produto=item['produto'],
                quantidade=int(item['quantidade']),
                valor_unitario=float(item['valor_unitario']),
                valor_subtotal=float(item['valor_subtotal'])
            ))

        db.session.commit()
        return jsonify({"mensagem": "Venda atualizada!"}), 200

    clientes = sorted(Cliente.query.all(), key=lambda c: c.nome_exibicao or c.nome)
    vendedores = Vendedor.query.order_by(Vendedor.nome).all()
    return render_template('editar_venda.html', venda=venda, clientes=clientes, vendedores=vendedores)

@app.route('/vendas/<int:id>/excluir', methods=['POST'])
def excluir_venda(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda = Venda.query.get(id)
    if not venda:
        flash('Venda não encontrada.', 'erro')
        return redirect(url_for('relatorio_vendas'))

    for item in venda.itens:
        db.session.delete(item)
    db.session.delete(venda)
    db.session.commit()
    flash(f'Venda #{id} excluída com sucesso!', 'sucesso')
    return redirect(url_for('relatorio_vendas'))

@app.route('/vendas/<int:id>/marcar_paga', methods=['POST'])
def marcar_venda_paga(id):
    if not usuario_esta_logado():
        return redirect(url_for('login'))

    venda = Venda.query.get_or_404(id)

    if request.form.get('desfazer'):
        venda.paga = False
        venda.data_pagamento = None
        flash(f'Pagamento da venda #{id} revertido.', 'sucesso')
    else:
        data_pagamento_str = request.form.get('data_pagamento')
        if data_pagamento_str:
            venda.data_pagamento = datetime.strptime(data_pagamento_str, '%Y-%m-%d')
        else:
            venda.data_pagamento = agora_brasil()
        venda.paga = True
        flash(f'Venda #{id} marcada como paga!', 'sucesso')
    db.session.commit()

    destino = request.referrer or url_for('relatorio_vendas')
    if destino and 'login' not in destino and url_for('login') not in destino:
        return redirect(destino)
    return redirect(url_for('relatorio_vendas'))

@app.route('/relatorios/comissao')
def relatorio_comissao():
    if not usuario_esta_logado():
        return redirect(url_for('login'))
    args = request.args.to_dict()
    args['relatorio'] = 'comissao'
    return redirect(url_for('relatorios', **args))

TIPOS_HISTORICO = ['WhatsApp', 'Telefone', 'E-mail', 'Amostra', 'Visita', 'Negociação', 'Outro']

def prospeccoes_com_acao_vencida():
    """Prospecções ativas cuja próxima ação já chegou, da mais urgente para a menos."""
    agora = agora_brasil()
    candidatos = Prospeccao.query.filter(
        Prospeccao.status.in_(Prospeccao.STATUS_ATIVOS),
        Prospeccao.proxima_acao_data.isnot(None),
        Prospeccao.proxima_acao_data <= agora,
    ).all()
    vencidas = [p for p in candidatos if p.proxima_acao_dt and p.proxima_acao_dt <= agora]
    vencidas.sort(key=lambda p: p.proxima_acao_dt)
    return vencidas

@app.route('/prospeccoes/verificar_acoes')
def verificar_acoes_json():
    if not usuario_esta_logado():
        return jsonify({'acoes': []}), 401

    acoes = []
    for p in prospeccoes_com_acao_vencida():
        acoes.append({
            'id': p.id,
            'nome': p.nome,
            'descricao': p.proxima_acao_descricao or 'Sem descrição',
            'data': p.proxima_acao_dt.strftime('%d/%m/%Y'),
            'hora': p.proxima_acao_hora or '',
        })
    return jsonify({'acoes': acoes})

@app.route('/prospeccoes/<int:id>/postergar', methods=['POST'])
def postergar_acao(id):
    if not usuario_esta_logado():
        return jsonify({"erro": "Não autorizado"}), 401

    prospeccao = Prospeccao.query.get_or_404(id)
    minutos = request.form.get('minutos', type=int) or 60

    if not prospeccao.proxima_acao_data:
        return jsonify({"erro": "Prospecção sem próxima ação."}), 400

    dt_atual = prospeccao.proxima_acao_dt or agora_brasil()
    nova_dt = max(dt_atual, agora_brasil()) + timedelta(minutes=minutos)
    prospeccao.proxima_acao_data = nova_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    prospeccao.proxima_acao_hora = nova_dt.strftime('%H:%M')
    db.session.commit()

    return jsonify({
        "mensagem": "Ação postergada!",
        "nova_data": nova_dt.strftime('%d/%m/%Y'),
        "nova_hora": nova_dt.strftime('%H:%M'),
    }), 200

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
        proxima_hora = request.form.get('proxima_acao_hora')

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
            data_cadastro=agora_brasil(),
            proxima_acao_data=proxima_data,
            proxima_acao_hora=proxima_hora or None,
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

    hoje_formatado = agora_brasil().strftime('%Y-%m-%d')
    vencidas = {p.id: True for p in prospeccoes_com_acao_vencida()}
    return render_template('prospeccoes.html',
                           prospeccoes=lista,
                           todas=todas,
                           filtro=filtro,
                           vencidas=vencidas,
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
        prospeccao.proxima_acao_hora = request.form.get('proxima_acao_hora') or None
        prospeccao.proxima_acao_descricao = request.form.get('proxima_acao_descricao')
        db.session.commit()
        flash('Dados da prospecção atualizados!', 'sucesso')
        return redirect(url_for('detalhe_prospeccao', id=prospeccao.id))

    historico = sorted(prospeccao.historicos, key=lambda h: h.data, reverse=True)
    acao_vencida = bool(prospeccao.ativa and prospeccao.proxima_acao_dt
                        and prospeccao.proxima_acao_dt <= agora_brasil())
    return render_template('prospeccao_detalhe.html',
                           p=prospeccao,
                           historico=historico,
                           acao_vencida=acao_vencida,
                           statuses=['Em andamento', 'Amostra enviada', 'Negociação', 'Convertido', 'Perdido'],
                           tipos_historico=TIPOS_HISTORICO,
                           hoje=agora_brasil().strftime('%Y-%m-%d'))
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

    data = datetime.strptime(data_str, '%Y-%m-%d') if data_str else agora_brasil()

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
        data_cadastro=agora_brasil(),
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

def agendar_backup_automatico():
    try:
        arquivo = backup_mod.criar_backup()
        print(f"Backup automático gerado: {arquivo}")
    except Exception as e:
        print(f"Erro ao gerar backup automático: {e}")


def iniciar_agendador_backups():
    """Inicia o backup automático diário (03:00, horário de Brasília).

    No Flask em modo debug, o reloader roda o módulo duas vezes; o WERKZEUG_RUN_MAIN
    garante que o agendador só inicie no processo real. No gunicorn (Render) o módulo
    roda uma vez por worker, e o padrão é um único worker.
    A variável PETCRM_DISABLE_BACKGROUND desliga o agendador (usada em testes e CLI)."""
    if os.environ.get('PETCRM_DISABLE_BACKGROUND'):
        return
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return
    agendador = BackgroundScheduler(timezone='America/Sao_Paulo')
    agendador.add_job(agendar_backup_automatico, 'cron', hour=3, minute=0)
    agendador.start()


iniciar_agendador_backups()

@app.route('/backups', methods=['GET', 'POST'])
def backups():
    if not is_admin():
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            arquivo = backup_mod.criar_backup()
            flash(f'Backup criado: {arquivo.name}', 'sucesso')
        except Exception as e:
            flash(f'Erro ao criar backup: {e}', 'erro')
        return redirect(url_for('backups'))

    lista = backup_mod.listar_backups()
    return render_template('backups.html', backups=lista, usuario_logado=session['usuario'])


@app.route('/backups/<path:nome>/baixar')
def baixar_backup(nome):
    if not is_admin():
        return redirect(url_for('login'))

    caminho = (backup_mod.BACKUP_DIR / nome).resolve()
    if not caminho.is_file() or caminho.parent != backup_mod.BACKUP_DIR.resolve():
        flash('Backup não encontrado.', 'erro')
        return redirect(url_for('backups'))
    return send_file(caminho, as_attachment=True)


@app.route('/backups/<path:nome>/excluir', methods=['POST'])
def excluir_backup(nome):
    if not is_admin():
        return redirect(url_for('login'))

    caminho = (backup_mod.BACKUP_DIR / nome).resolve()
    if caminho.is_file() and caminho.parent == backup_mod.BACKUP_DIR.resolve():
        caminho.unlink()
        flash(f'Backup "{nome}" excluído.', 'sucesso')
    return redirect(url_for('backups'))


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
