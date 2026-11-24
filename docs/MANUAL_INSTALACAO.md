# Manual de instalação e execução do GeoCNPJ

Este manual acompanha o [README](../README.md). O GeoCNPJ roda **na sua máquina**, pela URL `http://127.0.0.1:8092`. Abrir a aplicação não baixa automaticamente os arquivos da Receita. Na etapa de geocodificação, o pacote `geocodebr` pode baixar e guardar tabelas do CNEFE do IBGE em cache na primeira execução.

## Antes de começar

- **Python 3.11 ou superior**, com `pip` e `venv`. A combinação de versões fixada em `requirements.txt` foi verificada em uma instalação limpa no Windows com Python 3.13.17; outras plataformas/versões ainda exigem validação em máquina limpa.
- Internet para a instalação inicial dos pacotes, para consultar/baixar bases oficiais e para exibir o mapa base OpenStreetMap.
- Espaço em disco para pacotes e dados. O cache completo do CNEFE pode chegar a cerca de **1,2 GB**; os arquivos CNPJ de um mês completo podem ocupar vários GB. Confira o tamanho mostrado na etapa de download antes de escolher o destino.
- Permissão de escrita na pasta do projeto para criar `.venv`, `logs` e, por padrão, `data`.

Acesse [M-martins/GeoCNPJ](https://github.com/M-martins/GeoCNPJ), use **Code → Download ZIP** ou `git clone https://github.com/M-martins/GeoCNPJ.git`, e extraia em uma pasta onde você possa gravar arquivos. Não tente executar diretamente de dentro do ZIP. Não é preciso ter R, RStudio ou instalar `geocodebr` separadamente.

A etapa 1 baixa quatro ZIPs auxiliares do CNPJ e dois complementos compartilhados: a [lista de município/UF da Receita](https://www.gov.br/receitafederal/dados/municipios.csv/view) e a [planilha CNAE 2.3 do IBGE/Concla](https://cnae.ibge.gov.br/classificacoes/download-concla/8265-download). O primeiro é necessário para filtrar municípios por estado; sem a planilha CNAE, o processamento continua, mas não acrescenta seção, divisão e grupo. Ambos ficam na biblioteca local e podem ser inspecionados ou removidos no Acervo.

## Windows: iniciar com duplo clique

1. Instale o Python pelo site [python.org](https://www.python.org/downloads/). Durante a instalação, habilite a opção de adicionar Python ao `PATH` se ela aparecer.
2. Abra a pasta extraída do GeoCNPJ e dê duplo clique em **`iniciar.bat`**.
3. Na primeira vez, uma janela mostra a criação de `.venv` e a instalação dos pacotes de `requirements.txt`. Aguarde; a duração depende da conexão e da máquina. Em execuções seguintes, o inicializador apenas verifica as dependências.
4. Quando aparecer `GeoCNPJ pronto em http://127.0.0.1:8092`, o navegador abre a página inicial. Se ele não abrir, use esse endereço manualmente.

Para abrir novamente enquanto o servidor estiver ativo, use `http://127.0.0.1:8092` ou dê outro duplo clique em `iniciar.bat`. Após reiniciar o computador, execute `iniciar.bat` novamente. O inicializador mantém o servidor escutando somente em `127.0.0.1` e usa a porta 8092. Não execute o servidor com `--host 0.0.0.0` para oferecê-lo na internet; a aplicação foi projetada para uso local.

### Opções no PowerShell

Na pasta do projeto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\Abrir GeoCNPJ.ps1' -Check
powershell -NoProfile -ExecutionPolicy Bypass -File '.\Abrir GeoCNPJ.ps1' -SetupOnly
powershell -NoProfile -ExecutionPolicy Bypass -File '.\Abrir GeoCNPJ.ps1' -NoBrowser
```

`-Check` verifica Python e pacotes, sem instalar nem iniciar. `-SetupOnly` prepara o ambiente sem iniciar o servidor. `-NoBrowser` inicia sem abrir o navegador.

## macOS e Linux

Abra um terminal na pasta do projeto e execute:

```sh
python3 --version
python3 scripts/launch.py
```

O script cria `.venv`, instala os pacotes necessários, inicia o servidor local e tenta abrir o navegador. Se a distribuição Linux separar o módulo `venv` em um pacote do sistema, instale-o pelo gerenciador da distribuição e repita. A inicialização nessas plataformas ainda não foi validada em máquina limpa; consulte a seção de limitações abaixo.

Para apenas verificar ou preparar:

```sh
python3 scripts/launch.py --check
python3 scripts/launch.py --setup-only
python3 scripts/launch.py --no-browser
```

## Onde ficam os dados

Por padrão, `.venv/`, `data/` e `logs/` são criados na pasta do projeto. Para guardar **dados** em outro disco, defina `GEOCNPJ_DATA_DIR` antes de iniciar. Exemplo no PowerShell:

```powershell
$env:GEOCNPJ_DATA_DIR = 'D:\GeoCNPJ_Dados'
.\iniciar.bat
```

A aplicação registra os projetos, downloads, resultados e cache de geocodificação nesse destino. O navegador não envia os dados a um servidor externo do GeoCNPJ; a consulta ao WebDAV da Receita, o cache CNEFE do `geocodebr` e os tiles de mapa usam conexões de rede próprias.

## Primeiro uso

1. Na página inicial, abra **Etapas**.
2. Escolha o mês dos dados e as partes de Estabelecimentos que deseja baixar. A interface informa origem, tamanho e destino. Para cobertura municipal completa, baixe todas as partes do mês; partes isoladas podem ser processadas com aviso de cobertura parcial.
3. Escolha UF e município, prepare a base em CSV ou Parquet.
4. Inicie a geocodificação e acompanhe o andamento. A primeira execução pode demorar mais porque o `geocodebr` baixa as tabelas de referência do CNEFE.
5. Abra o mapa e revise os resultados antes de interpretar coordenadas como localização exata.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| “Python não foi encontrado” ou versão inferior a 3.11 | Instale Python 3.11+ e reabra o terminal. Execute `py -3 --version` (Windows) ou `python3 --version`. |
| Falha ao criar `.venv` | Verifique permissão de escrita e espaço livre. Em Linux, confira se `venv` está instalado. Não copie `.venv` de outra máquina. |
| Falha no `pip install` | Confira internet/proxy, espaço livre e se a versão do Python é compatível. Repita o inicializador; `pip` reutiliza o que já foi instalado. |
| A porta 8092 está ocupada | Feche a instância anterior. Se outro aplicativo usa a porta, libere-a antes de tentar novamente. |
| O navegador não abriu | Acesse `http://127.0.0.1:8092` manualmente. |
| Servidor não iniciou | Leia `logs/server.err.log`. Rode `python scripts/launch.py --check` para verificar os pacotes. |
| Não há espaço para dados | Escolha outro destino na etapa de download ou configure `GEOCNPJ_DATA_DIR` antes de iniciar. |

Se um ambiente `.venv` **copiado de outra máquina** estiver quebrado, remova apenas essa pasta depois de confirmar que não contém trabalho próprio e inicie novamente; o script cria uma nova. Não apague `data/` para resolver problemas de instalação, pois ela pode conter bases e projetos do usuário.

## Reprodutibilidade e limites

`requirements.txt` fixa as versões **diretas** usadas nesta cópia e o inicializador usa `pip check` para detectar incompatibilidades nas dependências instaladas. Ainda falta um lock com hashes para todas as dependências transitivas e validação de instalação limpa em macOS e Linux. Os arquivos CNPJ, cache CNEFE e resultados não devem ser incluídos no repositório: cada usuário obtém os dados das fontes indicadas na interface. A documentação de fontes, licenças e privacidade deve acompanhar a publicação do código.
