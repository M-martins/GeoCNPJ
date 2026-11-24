# GeoCNPJ

O GeoCNPJ transforma dados públicos de estabelecimentos do CNPJ em uma base municipal e um mapa para exploração e revisão. É um projeto de aprendizado desenvolvido por **[Márcio Martins](https://www.linkedin.com/in/marcio-martins-geo/)** com auxílio de **ChatGPT e Codex**. A aplicação roda em `127.0.0.1:8092`; arquivos, projetos e resultados ficam na máquina do usuário.

## Baixar, instalar e abrir

**Requisitos:** Python 3.11 ou superior (com `pip` e `venv`), internet na primeira instalação e permissão para gravar na pasta extraída. Não é necessário instalar R nem o geocodebr separadamente. Os dados da Receita e do CNEFE não acompanham o código; eles são obtidos nas etapas da aplicação.

### Windows

1. Instale o [Python](https://www.python.org/downloads/) e marque **Add python.exe to PATH** durante a instalação, se a opção aparecer.
2. Abra [o repositório no GitHub](https://github.com/M-martins/GeoCNPJ), clique em **Code → Download ZIP**, extraia o ZIP e abra a pasta extraída. Não execute o projeto de dentro do ZIP compactado.
3. Dê duplo clique em **`iniciar.bat`**. Na primeira execução, ele cria `.venv` e instala automaticamente os pacotes de `requirements.txt`; aguarde a conclusão na janela. Em usos seguintes, verifica as dependências e inicia sem reinstalar tudo.
4. A página inicial abre no navegador. Se isso não acontecer, acesse **http://127.0.0.1:8092**. Deixe o projeto na pasta extraída: nela ficam o ambiente Python e, por padrão, os dados.

**Para usar novamente:** se a aplicação já estiver rodando, basta abrir `http://127.0.0.1:8092`; clicar em `iniciar.bat` também abre a página existente. Depois de reiniciar o computador, dê duplo clique em `iniciar.bat` para iniciar o servidor local outra vez.

### macOS e Linux

Instale Python 3.11+ com `pip` e `venv`, baixe e extraia o ZIP do mesmo repositório ou use `git clone`. Abra um terminal na pasta do projeto e execute:

```sh
python3 scripts/launch.py
```

O script prepara `.venv`, inicia o servidor local e tenta abrir o navegador. Se necessário, acesse `http://127.0.0.1:8092`. A instalação limpa foi verificada no Windows; macOS e Linux ainda precisam de validação em máquinas dessas plataformas.

O primeiro uso pode baixar pacotes e dados grandes. Antes de escolher um mês completo, confira o espaço indicado na etapa 1. Para guardar **dados** em outro disco, configure `GEOCNPJ_DATA_DIR` antes de iniciar. Veja o [manual de instalação](docs/MANUAL_INSTALACAO.md) para exemplos, diagnóstico, opções do inicializador e local dos arquivos.

## Fluxo

1. **Dados oficiais:** escolha o mês dos dados de interesse. O GeoCNPJ consulta o catálogo público da Receita Federal/SERPRO e baixa os ZIPs selecionados para o computador. As referências `Cnaes.zip`, `Municipios.zip`, `Motivos.zip` e `Paises.zip` são compartilhadas entre projetos. O Acervo mostra os arquivos existentes e permite gerenciá-los.
2. **Base municipal:** escolha UF e município. O programa lê os ZIPs em blocos, separa registros do município e cria CSV ou Parquet. É possível usar só parte dos arquivos do mês; o aviso de cobertura parcial e a lista de partes usadas ficam registrados no resultado.
3. **Geocodificação:** o pacote Python [geocodebr do Ipea](https://github.com/ipea/geocodebr) compara endereços com insumos CNEFE/IBGE, propõe coordenadas e informa a precisão do pareamento. O GeoCNPJ calcula o score e indica os registros para revisão. A primeira execução pode baixar dados para o cache local.
4. **Mapa e revisão:** MapLibre mostra os pontos sobre tiles do OpenStreetMap. O usuário filtra, confere casos incertos e exporta CSV/GeoJSON. O índice local SQLite evita transferir todos os pontos para o navegador.

`Cnaes.zip` vem da base CNPJ da Receita e traduz códigos de atividade. A planilha CNAE 2.3 vem do [IBGE/Concla](https://cnae.ibge.gov.br/classificacoes/download-concla/8265-download) e acrescenta seção, divisão e grupo; se faltar, o processamento segue sem esse detalhe. `Municipios.zip` traz código e nome, mas não UF. Por isso a etapa 1 também obtém uma [lista complementar da Receita](https://www.gov.br/receitafederal/dados/municipios.csv/view) para relacionar código e estado. Esses dois complementos ficam no Acervo e não são embutidos no pacote de código.

## Tecnologias e conexão

| Parte | Tecnologia | Função |
|---|---|---|
| Navegador | HTML, CSS e JavaScript | Passo a passo, ajuda, Acervo e revisão. |
| Servidor local | Python e FastAPI | API, validação, tarefas e progresso. |
| Preparação | Leitura em blocos, Pandas e PyArrow | Filtragem municipal e arquivos CSV/Parquet. |
| Estado e mapa | SQLite | Projetos, operações, revisões e índice espacial. |
| Endereços | geocodebr em Python | Correspondência com CNEFE e coordenadas. |
| Visualização | MapLibre e OpenStreetMap | Mapa, agrupamentos e contexto cartográfico. |

A internet é usada para instalar pacotes Python, consultar/baixar dados da Receita, obter os complementos municipais e CNAE 2.3, obter insumos CNEFE quando necessário e carregar o MapLibre por `unpkg.com` e tiles de `tile.openstreetmap.org`. O navegador conversa com o servidor local; a aplicação não deve ser exposta em `0.0.0.0` ou publicada como servidor web. O mapa base e downloads não funcionam integralmente offline.

## Arquivos e publicação

Por padrão, downloads, cache, projetos e resultados ficam em `data/`; logs em `logs/`. Defina `GEOCNPJ_DATA_DIR` para guardar dados em outro disco. O termo técnico **competência** permanece em nomes internos de pastas e campos de API; na interface significa **mês dos dados**.

Esta distribuição de código não inclui os ZIPs CNPJ, o cache CNEFE nem resultados de usuários. O código do GeoCNPJ está sob [licença MIT](LICENSE); dados e pacotes de terceiros seguem seus próprios termos. Veja também o [repositório oficial](https://github.com/M-martins/GeoCNPJ) e as [orientações de publicação](docs/PREPARACAO_GITHUB.md).
