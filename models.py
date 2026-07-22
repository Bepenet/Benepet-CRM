from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True, nullable=False)
    senha = db.Column(db.String(256), nullable=False)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cpf_cnpj = db.Column(db.String(20))
    endereco = db.Column(db.String(255))
    telefone = db.Column(db.String(20))  # Whats/Tel
    contato = db.Column(db.String(100))  # Pessoa de contato
    data_cadastro = db.Column(db.DateTime, nullable=False)
    dias_aviso = db.Column(db.Integer, default=30)  # 7, 15 ou 30 dias
    periodo_retorno = db.Column(db.Integer, default=30)  # Mantido por compatibilidade

    @property
    def ultima_venda_data(self):
        """Data da venda mais recente desse cliente, ou None se nunca comprou."""
        if self.vendas:
            return max(v.data for v in self.vendas)
        return None

    @property
    def proximo_contato(self):
        """Data em que o cliente deve ser contatado novamente."""
        base = self.ultima_venda_data or self.data_cadastro
        return base + timedelta(days=self.dias_aviso or 30)

    @property
    def precisa_contato(self):
        """True se já passou (ou é hoje) a data de contato."""
        return datetime.utcnow() >= self.proximo_contato

    @property
    def dias_para_contato(self):
        """Quantos dias faltam (negativo = já passou do prazo)."""
        delta = self.proximo_contato - datetime.utcnow()
        return delta.days

class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    data = db.Column(db.DateTime, nullable=False)
    valor_total = db.Column(db.Float, nullable=False)
    prazo_pagamento = db.Column(db.String(50))

    cliente = db.relationship('Cliente', backref=db.backref('vendas', lazy=True))

class ItemVenda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey('venda.id'), nullable=False)
    produto = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    valor_subtotal = db.Column(db.Float, nullable=False)

    venda = db.relationship('Venda', backref=db.backref('itens', lazy=True))
