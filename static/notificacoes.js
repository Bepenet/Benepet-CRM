(function () {
    var notificadas = {};

    function verificarAcoes() {
        fetch('/prospeccoes/verificar_acoes')
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (dados) {
                if (!dados || !dados.acoes) return;
                dados.acoes.forEach(function (acao) {
                    if (notificadas[acao.id]) return;
                    notificadas[acao.id] = true;
                    mostrarPopup(acao);
                });
            })
            .catch(function () {});
    }

    function mostrarPopup(acao) {
        if (document.getElementById('popup-acao')) return;

        var overlay = document.createElement('div');
        overlay.id = 'popup-acao';
        overlay.style.cssText =
            'position:fixed;inset:0;background:rgba(15,23,42,0.55);z-index:9999;' +
            'display:flex;align-items:center;justify-content:center;padding:20px;';

        var card = document.createElement('div');
        card.style.cssText =
            'background:#fff;border-radius:14px;max-width:420px;width:100%;' +
            'box-shadow:0 20px 50px rgba(0,0,0,0.3);overflow:hidden;font-family:Segoe UI,Tahoma,sans-serif;';

        var cabecalho = document.createElement('div');
        cabecalho.style.cssText =
            'background:#f59e0b;color:#fff;padding:16px 20px;font-size:16px;font-weight:700;';
        cabecalho.textContent = '⏰ Hora de agir!';

        var corpo = document.createElement('div');
        corpo.style.cssText = 'padding:20px;color:#1e293b;';

        var nome = document.createElement('div');
        nome.style.cssText = 'font-size:18px;font-weight:700;margin-bottom:8px;';
        nome.textContent = acao.nome;

        var desc = document.createElement('div');
        desc.style.cssText = 'font-size:15px;color:#475569;margin-bottom:12px;';
        desc.textContent = acao.descricao;

        var quando = document.createElement('div');
        quando.style.cssText = 'font-size:13px;color:#92400e;font-weight:600;';
        quando.textContent = 'Agendada para ' + acao.data + (acao.hora ? ' às ' + acao.hora : '');

        var botoes = document.createElement('div');
        botoes.style.cssText = 'display:flex;gap:10px;margin-top:20px;';

        var link = document.createElement('a');
        link.href = '/prospeccoes/' + acao.id;
        link.textContent = 'Abrir prospecção';
        link.style.cssText =
            'background:#f59e0b;color:#fff;text-decoration:none;padding:10px 16px;' +
            'border-radius:6px;font-weight:700;font-size:14px;text-align:center;flex:1;';

        var botao = document.createElement('button');
        botao.type = 'button';
        botao.textContent = 'Entendi';
        botao.style.cssText =
            'background:#f1f5f9;color:#475569;border:none;padding:10px 16px;' +
            'border-radius:6px;font-weight:700;font-size:14px;cursor:pointer;';
        botao.onclick = function () { document.body.removeChild(overlay); };

        corpo.appendChild(nome);
        corpo.appendChild(desc);
        corpo.appendChild(quando);
        corpo.appendChild(botoes);
        botoes.appendChild(link);
        botoes.appendChild(botao);
        card.appendChild(cabecalho);
        card.appendChild(corpo);
        overlay.appendChild(card);
        document.body.appendChild(overlay);
    }

    verificarAcoes();
    setInterval(verificarAcoes, 30000);
})();
