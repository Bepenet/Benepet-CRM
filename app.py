from flask import Flask, render_template, request, redirect, session
from models import db, Usuario, Cliente, Venda
from datetime import datetime, date, timedelta
import re

app = Flask(__name__)

# CHAVE DE SEGURANÇA: Necessária para ativar o recurso de 'session' (pode deixar esse texto mesmo)
app.secret_key = "chave_secreta_benepet"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///petcrm.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

def limpar_telefone(telefone):
    if not telefone:
        return ""
    return re.sub(r"\D", "", telefone)

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario_digitado = request.form.get("usuario")
        senha_digitada = request.form.get("senha")

        usuario = Usuario.query.filter_by(nome=usuario_digitado).first()

        if usuario and usuario.verificar_senha(senha_digitada):
            # Salva o nome do usuário logado na sessão
            session["usuario_logado"] = usuario.nome
            return redirect("/dashboard")

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    hoje_str = date.today().strftime("%Y-%m-%d")

    total_clientes = Cliente.query.count()
    total_vendas = Venda.query.count()
    
    todas_vendas = Venda.query.all()
    faturamento = sum(v.valor for v in todas_vendas)

    todos_clientes = Cliente.query.all()
    clientes_para_contato = []
    for c in todos_clientes:
        if c.proximo_contato and c.proximo_contato <= hoje_str:
            clientes_para_contato.append(c)

    total_retornos = len(clientes_para_contato)

    # Pega quem está logado (se não tiver ninguém, assume vazio)
    usuario_atual = session.get("usuario_logado", "")

    return render_template(
        "dashboard.html",
        total_clientes=total_clientes,
        total_vendas=total_vendas,
        faturamento=faturamento,
        total_retornos=total_retornos,
        clientes_retorno=clientes_para_contato,
        hoje=date.today().strftime("%d/%m/%Y"),
        usuario_atual=usuario_atual # Envia para o HTML saber quem é
    )

@app.route("/clientes", methods=["GET", "POST"])
def clientes():
    if request.method == "POST":
        telefone_limpo = limpar_telefone(request.form.get("telefone"))
        
        dias_retorno = request.form.get("dias_retorno")
        data_proximo_contato = ""
        
        if dias_retorno:
            hoje = date.today()
            proximo = hoje + timedelta(days=int(dias_retorno))
            data_proximo_contato = proximo.strftime("%Y-%m-%d")

        novo_cliente = Cliente(
            nome=request.form.get("nome"),
            telefone=telefone_limpo,
            cidade=request.form.get("cidade"),
            produto=request.form.get("produto"),
            data_compra=request.form.get("data_compra"),
            proximo_contato=data_proximo_contato,
            observacao=request.form.get("observacao")
        )

        db.session.add(novo_cliente)
        db.session.commit()

        return redirect("/clientes")

    lista_clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template("clientes.html", clientes=lista_clientes)

@app.route("/excluir/<int:id>")
def excluir_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    return redirect("/clientes")

@app.route("/vendas", methods=["GET", "POST"])
def vendas():
    if request.method == "POST":
        nova_venda = Venda(
            cliente_id=int(request.form.get("cliente_id")),
            produto=request.form.get("produto"),
            valor=float(request.form.get("valor")),
            data_venda=request.form.get("data_venda")
        )
        db.session.add(nova_venda)
        db.session.commit()
        return redirect("/vendas")

    lista_vendas = Venda.query.order_by(Venda.data_venda.desc()).all()
    lista_clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template("vendas.html", vendas=lista_vendas, clientes=lista_clientes)

@app.route("/excluir_venda/<int:id>")
def excluir_venda(id):
    venda = Venda.query.get_or_404(id)
    db.session.delete(venda)
    db.session.commit()
    return redirect("/vendas")

@app.route("/dar_baixa/<int:id>", methods=["POST"])
def dar_baixa(id):
    cliente = Cliente.query.get_or_404(id)
    produto_atualizado = request.form.get("produto")
    dias_para_somar = int(request.form.get("dias"))
    
    hoje = date.today()
    proximo = hoje + timedelta(days=dias_para_somar)
    
    cliente.produto = produto_atualizado
    cliente.data_compra = hoje.strftime("%Y-%m-%d")
    cliente.proximo_contato = proximo.strftime("%Y-%m-%d")
    
    db.session.commit()
    return redirect("/dashboard")

@app.route("/usuarios", methods=["GET", "POST"])
def usuarios():
    # 🛑 SEGURANÇA: Se não for o 'admin', bloqueia o acesso e manda pro dashboard
    if session.get("usuario_logado") != "admin":
        return redirect("/dashboard")

    if request.method == "POST":
        nome_usuario = request.form.get("usuario").strip()
        senha_usuario = request.form.get("senha")

        existe = Usuario.query.filter_by(nome=nome_usuario).first()
        if not existe and nome_usuario and senha_usuario:
            novo_usuario = Usuario(nome=nome_usuario)
            novo_usuario.criar_senha(senha_usuario)
            db.session.add(novo_usuario)
            db.session.commit()
        return redirect("/usuarios")

    lista_usuarios = Usuario.query.order_by(Usuario.nome).all()
    return render_template("usuarios.html", usuarios=lista_usuarios)

@app.route("/excluir_usuario/<int:id>")
def excluir_usuario(id):
    # 🛑 SEGURANÇA: Se não for o 'admin', bloqueia a exclusão
    if session.get("usuario_logado") != "admin":
        return redirect("/dashboard")

    usuario = Usuario.query.get_or_404(id)
    if usuario.nome != "admin":
        db.session.delete(usuario)
        db.session.commit()
    return redirect("/usuarios")

# Adicionado recurso para fazer logout (voltar para a tela de login)
@app.route("/logout")
def logout():
    session.pop("usuario_logado", None)
    return redirect("/")

with app.app_context():
    db.create_all()
    if Usuario.query.count() == 0:
        usuario_padrao = Usuario(nome="admin")
        usuario_padrao.criar_senha("admin123")
        db.session.add(usuario_padrao)
        db.session.commit()
        print("👉 Usuário padrão 'admin' criado com sucesso!")

import os

if __name__ == "__main__":
    # O Render define automaticamente uma porta na variável de ambiente PORT
    porta = int(os.environ.get("PORT", 5000))
    # Vincula o host a 0.0.0.0 para que o Render consiga acessar
    app.run(host="0.0.0.0", port=porta, debug=False)