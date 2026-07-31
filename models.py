from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True, nullable=False)
    senha = db.Column(db.String(256), nullable=False)
    precisa_trocar_senha = db.Column(db.Boolean, default=True)

class Vendedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    telefone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    endereco = db.Column(db.String(255))
    cep = db.Column(db.String(10))
    cidade = db.Column(db.String(100))
    uf = db.Column(db.String(2))
    comissao_pct = db.Column(db.Float, default=0)  # percentual de comissão sobre vendas

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)  # Razão Social
    nome_fantasia = db.Column(db.String(100))
    cpf_cnpj = db.Column(db.String(20))
    endereco = db.Column(db.String(255))
    cep = db.Column(db.String(10))
    cidade = db.Column(db.String(100))
    uf = db.Column(db.String(2))
    telefone = db.Column(db.String(20))  # Whats/Tel
    email = db.Column(db.String(120))  # E-mail
    contato = db.Column(db.String(100))  # Pessoa de contato
    vendedor = db.Column(db.String(100))  # Vendedor responsável pelo atendimento
    data_cadastro = db.Column(db.DateTime, nullable=False)
    dias_aviso = db.Column(db.Integer, default=30)  # 7, 15 ou 30 dias
    periodo_retorno = db.Column(db.Integer, default=30)  # Mantido por compatibilidade
    contato_adiado_ate = db.Column(db.DateTime)  # lembrete adiado manualmente até essa data
    contato_desconsiderado = db.Column(db.Boolean, default=False)  # lembrete ignorado permanentemente

    @property
    def nome_exibicao(self):
        """Nome usado para identificar o cliente nas telas: nome fantasia, com razão social como reserva."""
        return self.nome_fantasia or self.nome

    @property
    def ultima_venda_data(self):
        """Data da venda confirmada mais recente desse cliente (ignora consignações pendentes), ou None se nunca comprou."""
        vendas_confirmadas = [v for v in self.vendas if v.status == 'Confirmada']
        if vendas_confirmadas:
            return max(v.data_efetiva for v in vendas_confirmadas)
        return None

    @property
    def proximo_contato(self):
        """Data em que o cliente deve ser contatado novamente, já considerando um adiamento manual."""
        base = self.ultima_venda_data or self.data_cadastro
        data_calculada = base + timedelta(days=self.dias_aviso or 30)
        if self.contato_adiado_ate and self.contato_adiado_ate > data_calculada:
            return self.contato_adiado_ate
        return data_calculada

    @property
    def precisa_contato(self):
        """True se já passou (ou é hoje) a data de contato, e o lembrete não foi desconsiderado."""
        if self.contato_desconsiderado:
            return False
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
    tipo = db.Column(db.String(20), default='Normal')  # 'Normal' ou 'Consignado'
    status = db.Column(db.String(20), default='Confirmada')  # 'Confirmada' ou 'Pendente'
    data_confirmacao = db.Column(db.DateTime)  # quando uma consignação foi confirmada como vendida
    vendedor = db.Column(db.String(100))  # vendedor responsável pela venda
    paga = db.Column(db.Boolean, default=False)  # boleto pago
    data_pagamento = db.Column(db.DateTime)  # data em que o boleto foi pago

    cliente = db.relationship('Cliente', backref=db.backref('vendas', lazy=True))

    @property
    def data_efetiva(self):
        """Data que deve valer para relatórios: a de confirmação, se for uma consignação já confirmada."""
        if self.tipo == 'Consignado' and self.data_confirmacao:
            return self.data_confirmacao
        return self.data

class ItemVenda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    venda_id = db.Column(db.Integer, db.ForeignKey('venda.id'), nullable=False)
    produto = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    valor_subtotal = db.Column(db.Float, nullable=False)

    venda = db.relationship('Venda', backref=db.backref('itens', lazy=True))

class Prospeccao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20))
    contato = db.Column(db.String(100))  # Pessoa de contato
    vendedor = db.Column(db.String(100))
    observacoes = db.Column(db.Text)
    status = db.Column(db.String(30), default='Em andamento')
    data_cadastro = db.Column(db.DateTime, nullable=False)
    proxima_acao_data = db.Column(db.DateTime)  # lembrete de próxima ação
    proxima_acao_hora = db.Column(db.String(5))  # lembrete de próxima ação (HH:MM)
    proxima_acao_descricao = db.Column(db.String(255))
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'))
    cliente = db.relationship('Cliente', backref=db.backref('prospeccoes', lazy=True))

    STATUS_ATIVOS = ['Em andamento', 'Amostra enviada', 'Negociação']

    @property
    def ativa(self):
        return self.status in self.STATUS_ATIVOS

    @property
    def proxima_acao_dt(self):
        """Data e hora completas da próxima ação, ou None se não houver."""
        if not self.proxima_acao_data:
            return None
        dt = self.proxima_acao_data
        if self.proxima_acao_hora:
            try:
                h, m = self.proxima_acao_hora.split(':')
                dt = dt.replace(hour=int(h), minute=int(m))
            except ValueError:
                pass
        return dt

class HistoricoProspeccao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prospeccao_id = db.Column(db.Integer, db.ForeignKey('prospeccao.id'), nullable=False)
    data = db.Column(db.DateTime, nullable=False)
    tipo = db.Column(db.String(50), default='Outro')
    descricao = db.Column(db.Text, nullable=False)

    prospeccao = db.relationship('Prospeccao', backref=db.backref('historicos', lazy=True))
