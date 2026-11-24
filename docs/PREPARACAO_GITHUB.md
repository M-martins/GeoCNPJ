# Preparação para publicação no GitHub

Esta pasta é uma **cópia do código**, separada da instalação em uso. A cópia não contém `.venv/`, `data/` de trabalho, `logs/`, ZIPs CNPJ, cache CNEFE, bases municipais ou mapas gerados. Antes de abrir o repositório:

1. O perfil [LinkedIn de Márcio Martins](https://www.linkedin.com/in/marcio-martins-geo/) e o [repositório GeoCNPJ](https://github.com/M-martins/GeoCNPJ) estão no rodapé. Confira os links no navegador.
2. O **código** está sob [licença MIT](../LICENSE). O projeto usa dependências e dados de terceiros; a licença do código não muda os termos deles.
3. O complemento de município/UF vem da [Receita Federal](https://www.gov.br/receitafederal/dados/municipios.csv/view) e é baixado pelo usuário na etapa 1; não inclua uma cópia no repositório.
4. A planilha CNAE 2.3 é baixada do [IBGE/Concla](https://cnae.ibge.gov.br/classificacoes/download-concla/8265-download) na etapa 1. Não inclua cópias no repositório; confira os termos da fonte ao compartilhar resultados derivados.
5. Rode `python scripts/launch.py --check` após instalar as dependências, `python -m unittest discover -s tests -q` e teste um fluxo sintético. Uma instalação limpa em outros sistemas operacionais ainda não foi verificada.
6. Revise `git status` e os arquivos preparados antes do primeiro push. Não inclua dados baixados, resultados, `.env`, tokens ou caminhos pessoais.

A aplicação roda somente em `127.0.0.1`. Internet é usada por `pip` na instalação, pelo catálogo e downloads da Receita, pelo cache CNEFE/IBGE do geocodebr e pelo mapa (`unpkg.com` para MapLibre e `tile.openstreetmap.org` para os tiles). Não configure o servidor para exposição pública sem uma revisão específica de autenticação, isolamento e abuso de recursos.
