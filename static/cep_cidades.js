var CIDADES_POR_UF = window.CIDADES_POR_UF || {};

function mascaraCEP(input) {
    var v = input.value.replace(/\D/g, '');
    v = v.substring(0, 8);
    if (v.length > 5) v = v.substring(0, 5) + '-' + v.substring(5);
    input.value = v;
}

function carregarCidades(uf, selectCidade) {
    selectCidade.innerHTML = '<option value="">— Selecione a cidade —</option>';
    var cidades = CIDADES_POR_UF[uf];
    if (!cidades) return;
    cidades.forEach(function (nome) {
        var opt = document.createElement('option');
        opt.value = nome;
        opt.textContent = nome;
        selectCidade.appendChild(opt);
    });
}

function selecionarCidade(selectCidade, cidade) {
    if (!cidade) return;
    var opcoes = selectCidade.options;
    for (var i = 0; i < opcoes.length; i++) {
        if (opcoes[i].value === cidade) {
            opcoes[i].selected = true;
            return;
        }
    }
}

function inicializarCidade(selectUf, selectCidade, cidadeAtual) {
    var uf = selectUf.value;
    if (uf) {
        carregarCidades(uf, selectCidade);
        selecionarCidade(selectCidade, cidadeAtual);
    }
}

function aoTrocarUf(selectUf, selectCidade, cidadeAtual) {
    carregarCidades(selectUf.value, selectCidade);
    selecionarCidade(selectCidade, cidadeAtual);
}

function buscarCEP(inputCep, idEndereco, idCidade, idUf) {
    var cep = inputCep.value.replace(/\D/g, '');
    if (cep.length !== 8) {
        alert('Digite um CEP válido (8 dígitos).');
        return;
    }
    fetch('https://viacep.com.br/ws/' + cep + '/json/')
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.erro) {
                alert('CEP não encontrado.');
                return;
            }
            var partes = [];
            if (d.logradouro) partes.push(d.logradouro);
            if (d.bairro) partes.push(d.bairro);
            document.getElementById(idEndereco).value = partes.join(' - ');
            var selUf = document.getElementById(idUf);
            var selCidade = document.getElementById(idCidade);
            if (d.uf && CIDADES_POR_UF[d.uf]) {
                if (selUf.value !== d.uf) carregarCidades(d.uf, selCidade);
                selUf.value = d.uf;
                selecionarCidade(selCidade, d.localidade);
            }
        })
        .catch(function () {
            alert('Não foi possível buscar o CEP. Verifique sua conexão.');
        });
}
