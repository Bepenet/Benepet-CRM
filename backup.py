import io
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from models import db

BACKUP_DIR = Path('/data/backups') if os.path.isdir('/data') else Path('backups')
MANTER_BACKUPS = int(os.environ.get('MANTER_BACKUPS', 30))


def _pasta_backups():
    BACKUP_DIR.mkdir(exist_ok=True)
    return BACKUP_DIR


def criar_backup():
    """Cria um backup do banco atual (SQLite ou PostgreSQL) e devolve o caminho."""
    pasta = _pasta_backups()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    url = db.engine.url

    if url.drivername.startswith('sqlite'):
        destino = pasta / f'backup_{timestamp}.db'
        origem = sqlite3.connect(url.database)
        try:
            copia = sqlite3.connect(str(destino))
            try:
                origem.backup(copia)
            finally:
                copia.close()
        finally:
            origem.close()
    else:
        destino = pasta / f'backup_{timestamp}.sql'
        try:
            _dump_postgres_pg_dump(url, destino)
        except Exception:
            _dump_postgres_json(destino)

    rotacionar_backups()
    return destino


def _dump_postgres_pg_dump(url, destino):
    """Usa o pg_dump quando disponível no servidor (ex.: Render)."""
    uri = url.render_as_string(hide_password=False)
    env = dict(os.environ)
    if url.password:
        env['PGPASSWORD'] = url.password
    subprocess.run(
        ['pg_dump', uri, '--file', str(destino), '--no-owner'],
        env=env, check=True, capture_output=True, timeout=180,
    )


def _dump_postgres_json(destino):
    """Plano B (sem pg_dump): exporta todas as tabelas em JSON via SQLAlchemy."""
    dados = {}
    for tabela in db.metadata.sorted_tables:
        linhas = db.session.execute(db.select(tabela)).all()
        dados[tabela.name] = [
            {col.name: getattr(linha, col.name) for col in tabela.columns}
            for linha in linhas
        ]
    with open(destino, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=str)


def listar_backups():
    """Lista os backups existentes, do mais recente para o mais antigo."""
    pasta = _pasta_backups()
    arquivos = sorted(
        (p for p in pasta.iterdir() if p.is_file() and p.name.startswith('backup_')),
        key=lambda p: p.name,
        reverse=True,
    )
    return [
        {
            'nome': p.name,
            'tamanho': p.stat().st_size,
            'data': datetime.fromtimestamp(p.stat().st_mtime),
        }
        for p in arquivos
    ]


def rotacionar_backups(manter=MANTER_BACKUPS):
    """Apaga os backups mais antigos, mantendo apenas os `manter` mais recentes."""
    backups = sorted(
        _pasta_backups().glob('backup_*'),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for antigo in backups[manter:]:
        antigo.unlink(missing_ok=True)


DELIMITADOR_FIM_COPY = '\\.'
_PADRAO_COPY = re.compile(r'^COPY\s+(\S+)\s+\(([^)]*)\)\s+FROM\s+stdin\s*;?$')


def _decodificar_campo_copiar(campo):
    """Converte um campo do formato COPY do pg_dump (\\N para nulo e escapes
    como \\t, \\n) num valor Python bruto (str ou None)."""
    if campo == r'\N':
        return None
    if campo == '':
        return ''
    mapa = {'\\': '\\', 't': '\t', 'n': '\n', 'r': '\r'}
    saida = []
    i = 0
    while i < len(campo):
        if campo[i] == '\\' and i + 1 < len(campo):
            proximo = campo[i + 1]
            saida.append(mapa.get(proximo, proximo))
            i += 2
        else:
            saida.append(campo[i])
            i += 1
    return ''.join(saida)


def _converter_valor(coluna, valor):
    """Ajusta o valor bruto do COPY (string) para o tipo Python da coluna."""
    if valor is None:
        return None
    tipo = coluna.type.python_type
    if tipo is bool:
        return valor in ('t', '1')
    if tipo is int:
        try:
            return int(valor)
        except ValueError:
            return valor
    if tipo is float:
        try:
            return float(valor)
        except ValueError:
            return valor
    if tipo is datetime:
        for formato in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(valor, formato)
            except ValueError:
                continue
        return valor
    return valor


def analisar_dump(conteudo):
    """Separa um dump do pg_dump em instruções SQL e blocos de dados COPY.

    Devolve (instrucoes, blocos_copy), onde blocos_copy é uma lista de
    (tabela, colunas, linhas)."""
    instrucoes = []
    blocos_copy = []
    linhas = conteudo.splitlines()
    i = 0
    n = len(linhas)
    while i < n:
        atual = linhas[i].strip()
        if not atual or atual.startswith('--') or atual.startswith('\\'):
            i += 1
            continue
        match = _PADRAO_COPY.match(atual)
        if match:
            tabela = match.group(1).replace('"', '')
            colunas = [c.strip().replace('"', '') for c in match.group(2).split(',')]
            dados = []
            i += 1
            while i < n:
                linha = linhas[i]
                if linha == DELIMITADOR_FIM_COPY:
                    i += 1
                    break
                if linha.endswith(DELIMITADOR_FIM_COPY):
                    dados.append(linha[:-2])
                    i += 1
                    break
                dados.append(linha)
                i += 1
            blocos_copy.append((tabela, colunas, dados))
            continue
        bloco = [linhas[i]]
        primeira_linha = linhas[i].rstrip()
        i += 1
        if primeira_linha.endswith(';'):
            instrucoes.append('\n'.join(bloco))
            continue
        while i < n:
            linha = linhas[i]
            bloco.append(linha)
            i += 1
            if linha.rstrip().endswith(';'):
                break
        instrucoes.append('\n'.join(bloco))
    return instrucoes, blocos_copy


def _construir_registros(colunas, tabela_modelo, linhas):
    """Converte as linhas de um bloco COPY em dicionários prontos para INSERT.

    Colunas que não existem no modelo atual são ignoradas (dump antigo).
    Os valores passam pela decodificação \\N/escapes e pela conversão de tipo."""
    registros = []
    colunas_validas = [c for c in colunas if c in tabela_modelo.columns]
    if not colunas_validas:
        return registros
    for linha in linhas:
        campos = linha.split('\t')
        registro = {}
        for coluna_atual, valor in zip(colunas, campos):
            if coluna_atual not in colunas_validas:
                continue
            registro[coluna_atual] = _converter_valor(
                tabela_modelo.columns[coluna_atual],
                _decodificar_campo_copiar(valor),
            )
        registros.append(registro)
    return registros


def _ajustar_sequencias(conn):
    """Após importar dados com IDs explícitos, adianta as sequências de cada
    tabela para o maior id, evitando conflito nos próximos lançamentos."""
    for nome, tabela in db.metadata.tables.items():
        if 'id' not in tabela.columns or not tabela.columns['id'].primary_key:
            continue
        seq = conn.execute(
            text("SELECT pg_get_serial_sequence(:t, 'id')"),
            {'t': f'public.{nome}'},
        ).scalar()
        if not seq:
            continue
        maior = conn.execute(
            text(f'SELECT COALESCE(MAX(id), 0) FROM public."{nome}"'),
        ).scalar() or 0
        if not maior:
            continue
        conn.execute(text('SELECT setval(:seq, :maior, true)'),
                     {'seq': seq, 'maior': maior})


def _restaurar_dump_postgres(instrucoes, blocos_copy):
    """Restaura os DADOS de um dump do pg_dump no PostgreSQL de forma atômica.

    O esquema é recriado a partir dos modelos atuais do app (create_all), e só
    os dados (blocos COPY) são importados, casando colunas por nome. Isso
    evita problemas de privilégios (ALTER DEFAULT PRIVILEGES/OWNER), de versão
    do Postgres e de colunas que mudaram. Tudo roda numa única transação: se
    qualquer passo falhar, o banco volta ao estado anterior intacto.
    Devolve o total de registros importados."""
    total = 0
    with db.engine.begin() as conn:
        conn.execute(text('SET statement_timeout = 300000'))
        conn.execute(text('SET lock_timeout = 30000'))
        db.metadata.drop_all(bind=conn)
        db.metadata.create_all(bind=conn)
        for tabela, colunas, linhas in blocos_copy:
            nome = tabela.split('.')[-1]
            if not linhas or nome not in db.metadata.tables:
                continue
            registros = _construir_registros(colunas, db.metadata.tables[nome], linhas)
            if registros:
                conn.execute(db.metadata.tables[nome].insert().values(registros))
                total += len(registros)
        _ajustar_sequencias(conn)
    db.create_all()
    return total


def restaurar_backup_dump(conteudo):
    """Restaura um dump do pg_dump no banco atual, apagando os dados existentes.

    O esquema é recriado a partir dos modelos atuais e só os DADOS (blocos COPY)
    são importados, casando colunas por nome. Em PostgreSQL tudo roda numa única
    transação atômica. Devolve o total de registros importados."""
    instrucoes, blocos_copy = analisar_dump(conteudo)
    dialeto = db.engine.dialect.name
    total = 0

    tem_estrutura = any(
        i.strip().upper().startswith('CREATE TABLE') for i in instrucoes
    )
    if not tem_estrutura or not blocos_copy:
        raise ValueError(
            'O arquivo não parece ser um dump SQL válido (sem tabelas/COPY). '
            'Nenhum dado foi alterado — envie um backup gerado pela opção de backup.'
        )

    if dialeto == 'postgresql':
        return _restaurar_dump_postgres(instrucoes, blocos_copy)

    db.drop_all()
    db.create_all()
    for tabela, colunas, linhas in blocos_copy:
        nome = tabela.split('.')[-1]
        if not linhas or nome not in db.metadata.tables:
            continue
        registros = _construir_registros(colunas, db.metadata.tables[nome], linhas)
        for registro in registros:
            db.session.execute(db.metadata.tables[nome].insert().values(registro))
            total += 1
    db.session.commit()
    return total
