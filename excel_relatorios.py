"""Geração das planilhas .xlsx dos relatórios.

O módulo recebe o contexto já montado pela rota de relatórios (o mesmo usado no
template HTML) e devolve um arquivo Excel em memória, com uma aba por seção do
relatório. Não acessa o banco: apenas formata os dados que já vieram prontos.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

FMT_MOEDA = '"R$" #,##0.00'
FMT_PERCENTUAL = '0.00%'

FUNDO_CABECALHO = PatternFill('solid', fgColor='1E293B')
FONTE_CABECALHO = Font(bold=True, color='FFFFFF')
FONTE_TITULO = Font(bold=True, size=14)
FONTE_NEGRITO = Font(bold=True)
FUNDO_DESTAQUE = PatternFill('solid', fgColor='EEF2FF')


def _moeda(valor):
    return round(float(valor or 0), 2)


def _data(valor):
    return valor.strftime('%d/%m/%Y') if valor else ''


def _titulo(ws, texto):
    """Escreve um título em negrito na primeira linha e devolve a próxima linha livre."""
    celula = ws.cell(row=1, column=1, value=texto)
    celula.font = FONTE_TITULO
    return 3


def _escrever_tabela(ws, linha_inicial, cabecalhos, linhas, formatos=None):
    """Escreve cabeçalho e linhas a partir de `linha_inicial`.

    `formatos` é um mapa coluna (1-based) -> código de formato numérico do Excel.
    Devolve a próxima linha livre."""
    linha = linha_inicial
    for coluna, titulo in enumerate(cabecalhos, start=1):
        celula = ws.cell(row=linha, column=coluna, value=titulo)
        celula.font = FONTE_CABECALHO
        celula.fill = FUNDO_CABECALHO
        celula.alignment = Alignment(horizontal='center', vertical='center')
    linha += 1
    for registro in linhas:
        for coluna, valor in enumerate(registro, start=1):
            celula = ws.cell(row=linha, column=coluna, value=valor)
            if formatos and formatos.get(coluna):
                celula.number_format = formatos[coluna]
        linha += 1
    return linha


def _autosize(ws, minimo=12, maximo=45):
    larguras = {}
    for linha in ws.iter_rows():
        for celula in linha:
            if celula.value is None:
                continue
            larguras[celula.column] = max(larguras.get(celula.column, 0), len(str(celula.value)))
    for coluna, largura in larguras.items():
        ws.column_dimensions[get_column_letter(coluna)].width = min(max(largura + 2, minimo), maximo)


def _rotulo(contexto, padrao=''):
    return contexto.get('rotulo_periodo') or str(contexto.get('ano') or padrao)


def _sheet_historico_vendas(wb, ctx):
    ws = wb.create_sheet('Histórico de Vendas')
    linhas = [
        [
            venda.id,
            venda.cliente.nome_exibicao if venda.cliente else '',
            _data(venda.data),
            venda.prazo_pagamento or '',
            'Confirmada' if venda.status == 'Confirmada' else 'Consignado (Pendente)',
            'Pago' if venda.paga else 'Aguardando',
            _moeda(venda.valor_total),
        ]
        for venda in ctx.get('vendas_export', [])
    ]
    _escrever_tabela(
        ws, _titulo(ws, f'Histórico de Vendas Lançadas - {_rotulo(ctx)}'),
        ['ID', 'Cliente', 'Data', 'Prazo Pagamento', 'Status', 'Pagamento', 'Valor Total'],
        linhas, {7: FMT_MOEDA},
    )


def _sheet_vendas_por_vendedor(wb, ctx):
    ws = wb.create_sheet('Vendas por Vendedor')
    linhas = [
        [nome, dados['quantidade_vendas'], _moeda(dados['valor'])]
        for nome, dados in ctx.get('vendedores_resumo', [])
    ]
    _escrever_tabela(ws, _titulo(ws, f'Vendas por Vendedor - {_rotulo(ctx)}'),
                     ['Vendedor', 'Qtd. de Vendas', 'Total Vendido'],
                     linhas, {3: FMT_MOEDA})


def _sheet_vendas_por_cliente(wb, ctx):
    if not ctx.get('cliente_selecionado'):
        raise ValueError('Selecione um cliente para exportar este relatório.')
    ws = wb.create_sheet('Vendas por Cliente')
    linhas = [
        [
            venda.id,
            _data(venda.data),
            venda.prazo_pagamento or '',
            venda.tipo,
            'Confirmada' if venda.status == 'Confirmada' else 'Consignado (Pendente)',
            _moeda(venda.valor_total),
        ]
        for venda in ctx.get('vendas_cliente', [])
    ]
    _escrever_tabela(ws, 1,
                     ['ID', 'Data', 'Prazo de Pagamento', 'Tipo', 'Status', 'Valor Total'],
                     linhas, {6: FMT_MOEDA})


def _sheet_vendas_por_mes(wb, ctx):
    ws = wb.create_sheet('Vendas por Mês')
    linhas = [
        [dados['label'], dados['quantidade_vendas'], _moeda(dados['valor'])]
        for _chave, dados in ctx.get('meses_resumo', [])
    ]
    _escrever_tabela(ws, _titulo(ws, 'Vendas por Mês'), ['Mês', 'Qtd. de Vendas', 'Total Vendido'],
                     linhas, {3: FMT_MOEDA})


def _sheet_quantidade_produtos(wb, ctx):
    ws = wb.create_sheet('Quantidade de Produtos')
    linhas = [
        [produto, dados['quantidade'], _moeda(dados['valor'])]
        for produto, dados in ctx.get('produtos_resumo', [])
    ]
    _escrever_tabela(ws, _titulo(ws, 'Quantidade de Produtos Vendidos'),
                     ['Produto', 'Quantidade', 'Valor Vendido'], linhas, {3: FMT_MOEDA})


def _sheet_comissao(wb, ctx):
    resumo = ctx.get('resumo_comissao', {})
    ws = wb.create_sheet('Comissão')
    linhas = []
    total_valor = total_comissao = 0.0
    total_qtd = 0
    for nome, dados in resumo.items():
        pct = float(dados.get('pct') or 0)
        linhas.append([
            nome,
            dados['qtd'],
            _moeda(dados['total']),
            pct / 100.0,
            _moeda(dados.get('comissao')),
        ])
        total_valor += dados['total']
        total_comissao += dados.get('comissao') or 0
        total_qtd += dados['qtd']
    proxima = _escrever_tabela(
        ws, _titulo(ws, 'Comissão de Vendedores'),
        ['Vendedor', 'Boletos Pagos', 'Total Vendido', 'Comissão (%)', 'Comissão a Pagar'],
        linhas, {3: FMT_MOEDA, 4: FMT_PERCENTUAL, 5: FMT_MOEDA})
    if linhas:
        totais = [total_qtd, None, total_valor, None, total_comissao]
        linha_total = proxima
        for coluna, valor in enumerate(['Total Geral'] + totais, start=1):
            celula = ws.cell(row=linha_total, column=coluna, value=valor)
            celula.font = FONTE_NEGRITO
            celula.fill = FUNDO_DESTAQUE
        ws.cell(row=linha_total, column=3).number_format = FMT_MOEDA
        ws.cell(row=linha_total, column=5).number_format = FMT_MOEDA

    ws2 = wb.create_sheet('Boletos Pagos')
    linhas2 = [
        [
            _data(venda.data_pagamento),
            venda.id,
            venda.cliente.nome_exibicao if venda.cliente else '',
            venda.vendedor or '',
            _moeda(venda.valor_total),
            _moeda(getattr(venda, 'comissao_valor', 0)),
        ]
        for venda in ctx.get('vendas_pagas', [])
    ]
    _escrever_tabela(ws2, _titulo(ws2, 'Boletos Pagos no Período'),
                     ['Data Pagamento', 'Venda', 'Cliente', 'Vendedor', 'Valor', 'Comissão'],
                     linhas2, {5: FMT_MOEDA, 6: FMT_MOEDA})


def _sheet_historico_matriz(wb, ctx):
    ws = wb.create_sheet('Histórico de Vendas')
    meses = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    cabecalhos = ['Vendedor', 'Cliente'] + meses + ['Total']
    linha = _titulo(ws, f"Histórico de Vendas por Vendedor/Cliente - {ctx.get('ano', '')}")
    for coluna, titulo in enumerate(cabecalhos, start=1):
        celula = ws.cell(row=linha, column=coluna, value=titulo)
        celula.font = FONTE_CABECALHO
        celula.fill = FUNDO_CABECALHO
        celula.alignment = Alignment(horizontal='center', vertical='center')
    linha += 1

    def _escrever(valores, negrito=False, destaque=False):
        nonlocal linha
        for coluna, valor in enumerate(valores, start=1):
            celula = ws.cell(row=linha, column=coluna, value=valor)
            if coluna >= 3:
                celula.number_format = FMT_MOEDA
            if negrito:
                celula.font = FONTE_NEGRITO
            if destaque:
                celula.fill = FUNDO_DESTAQUE
        linha += 1

    for grupo in ctx.get('grupos_matriz', []):
        _escrever([grupo['vendedor'], ''] + [None] * 12 + [_moeda(grupo['total'])],
                  negrito=True, destaque=True)
        for cliente, dados in grupo['clientes']:
            _escrever(['', cliente] + [_moeda(m) if m else None for m in dados['meses']]
                      + [_moeda(dados['total'])])
    if ctx.get('grupos_matriz'):
        _escrever(['Total Geral', ''] + [_moeda(m) if m else None for m in ctx.get('totais_meses', [])]
                  + [_moeda(ctx.get('total_geral', 0))], negrito=True, destaque=True)


def _sheet_proximo_contato(wb, ctx):
    ws = wb.create_sheet('Próximo Contato')
    linhas = [
        [
            cliente.nome_exibicao,
            cliente.telefone or '',
            _data(cliente.ultima_venda_data) if cliente.ultima_venda_data else 'Nunca comprou',
            _data(cliente.proximo_contato),
        ]
        for cliente in ctx.get('clientes_contato', [])
    ]
    _escrever_tabela(ws, _titulo(ws, 'Próximo Contato'),
                     ['Cliente', 'Contato', 'Última Venda', 'Próximo Contato'], linhas)


def _sheet_parcelas(wb, ctx):
    ws = wb.create_sheet('Parcelas a Receber')
    linhas = []
    a_receber = vencido = recebido = 0.0
    qtd_vencidas = 0
    for item in ctx.get('parcelas_relatorio', []):
        parcela = item['parcela']
        if parcela.paga:
            situacao = f"Paga em {_data(parcela.data_pagamento)}" if parcela.data_pagamento else 'Paga'
            recebido += parcela.valor
        elif parcela.vencida:
            situacao = f'Vencida há {parcela.dias_atraso} dia(s)'
            vencido += parcela.valor
            a_receber += parcela.valor
            qtd_vencidas += 1
        else:
            situacao = 'A vencer'
            a_receber += parcela.valor
        linhas.append([
            parcela.venda_id,
            parcela.venda.cliente.nome_exibicao if parcela.venda and parcela.venda.cliente else '',
            f"{parcela.numero}/{item['total_na_venda']}",
            _data(parcela.vencimento),
            _moeda(parcela.valor),
            situacao,
        ])
    proxima = _escrever_tabela(
        ws, _titulo(ws, 'Parcelas a Receber'),
        ['Venda', 'Cliente', 'Parcela', 'Vencimento', 'Valor', 'Situação'],
        linhas, {5: FMT_MOEDA})

    proxima += 1
    resumo = [
        ('Parcelas no Período', len(linhas)),
        ('A Receber', _moeda(a_receber)),
        (f'Vencidas ({qtd_vencidas})', _moeda(vencido)),
        ('Recebido', _moeda(recebido)),
    ]
    for rotulo, valor in resumo:
        ws.cell(row=proxima, column=1, value=rotulo).font = FONTE_NEGRITO
        celula = ws.cell(row=proxima, column=2, value=valor)
        if isinstance(valor, float):
            celula.number_format = FMT_MOEDA
        proxima += 1


_CONSTRUTORES = {
    'historico_vendas': _sheet_historico_vendas,
    'vendas_por_vendedor': _sheet_vendas_por_vendedor,
    'vendas_por_cliente': _sheet_vendas_por_cliente,
    'vendas_por_mes': _sheet_vendas_por_mes,
    'quantidade_produtos': _sheet_quantidade_produtos,
    'comissao': _sheet_comissao,
    'historico_matriz': _sheet_historico_matriz,
    'proximo_contato': _sheet_proximo_contato,
    'parcelas': _sheet_parcelas,
}


def gerar_planilha(contexto):
    """Constrói a planilha do relatório indicado em `contexto['tipo']`.

    Devolve um BytesIO posicionado no início, pronto para send_file. Levanta
    ValueError quando o relatório não existe ou exige um filtro não informado."""
    tipo = contexto.get('tipo')
    construtor = _CONSTRUTORES.get(tipo)
    if not construtor:
        raise ValueError('Selecione um relatório para exportar.')

    wb = Workbook()
    wb.remove(wb.active)
    construtor(wb, contexto)
    if not wb.sheetnames:
        wb.create_sheet('Relatório')

    for ws in wb.worksheets:
        _autosize(ws)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
