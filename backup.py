import json
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from models import db

BACKUP_DIR = Path('backups')
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
