# Revisão de desempenho e segurança do GeoCNPJ

Revisão do código da GeoCNPJ em 22–23/11/2026. Os ganhos abaixo são hipóteses de engenharia, não percentuais medidos em uma base completa. A verificação de projetos usou um banco temporário com 20 projetos; nenhum download ou processamento nacional foi repetido nesta revisão.

## Alterações aplicadas

- A listagem de projetos passa a consultar prontidão, processos e geocodificações uma vez por requisição, em vez de uma vez por projeto. Com 20 projetos de teste, foram 1+1+1 consultas lógicas.
- Escritas em `/api` e `/geo` vindas de outra origem são recusadas; o host aceito é local. A configuração CORS do motor GEO deixou de aceitar qualquer origem.
- O motor GEO valida identificadores de jobs e caminhos antes de servir arquivos; o número de núcleos solicitado fica limitado aos núcleos disponíveis.
- O mês registrado no Acervo precisa ter formato `AAAA-MM`; nomes, mensagens e logs mais expostos no fluxo e no stepper são escapados antes de entrar no HTML.
- A landing page descreve o Acervo compartilhado, o processamento parcial, as fontes, a pilha técnica e as quatro entregas do fluxo.
- Uploads CSV/Parquet do motor GEO agora têm limite configurável (`GEOCNPJ_MAX_UPLOAD_BYTES`, padrão 2 GiB), cópia em blocos, remoção do arquivo parcial e recusa antecipada pelo cabeçalho `Content-Length` quando presente. A cópia roda fora da thread do servidor.
- Exportações CSV do mapa prefixam textos que planilhas poderiam executar como fórmula. O GeoJSON e os dados internos preservam os valores originais.
- Filtros e buscas do mapa têm limite de comprimento; a lista de seleção limita 500 registros e páginas fora do intervalo são recusadas.
- A construção do índice do mapa insere lotes de mil registros no SQLite, sem acumular uma segunda lista completa de linhas. Arquivos acima de 4 MiB agora são lidos em fluxo; os menores usam o parser integral mais rápido.
- Identificadores usados em handlers e atributos HTML do Acervo são serializados e escapados. A revisão continua recomendando migrar os handlers inline para eventos delegados.

## Desempenho: prioridades

| Prioridade | Evidência no código | Melhoria proposta | Como medir |
| --- | --- | --- | --- |
| Alta | `backend/processor.py`, `_process_zip`: cada município lê todas as linhas dos ZIPs nacionais escolhidos. | Criar, por mês e assinatura dos ZIPs, um índice local reutilizável por município. Construí-lo uma vez; consultas seguintes leem apenas o recorte. Prever espaço em disco e invalidar ao mudar os arquivos. | Tempo da primeira base, da segunda base do mesmo mês, bytes lidos e espaço do índice. |
| Aplicada | `backend/processor.py`, `_finish`: CSV e Parquet agora são mesclados em lotes de 50 mil linhas. | Medir em municípios grandes e ajustar o tamanho do lote conforme memória disponível. | Pico de memória, tempo de finalização, tamanho e equivalência dos arquivos. |
| Aplicada | GeoJSONs grandes agora são lidos em fluxo na preparação do mapa e no índice SQLite; o arquivo completo é escrito por feição. | Medir a abertura com mapas reais; avaliar índice espacial RTree se o viewport continuar lento. | Tempo para abrir primeiro mapa, pico de memória e latência do viewport. |
| Aplicada | O progresso da leitura dos ZIPs é persistido no primeiro bloco, depois no máximo a cada 2 segundos e ao terminar cada arquivo. | Comparar a leitura nacional antes/depois com o mesmo ZIP. | Linhas/s, gravações por milhão de linhas e precisão do progresso. |
| Média | `backend/map_index.py`, `records` e `viewport`: o filtro de revisão traz muitos registros para Python; buscas `LIKE '%texto%'` não usam bem índices B-tree. | Indexar o estado de revisão e avaliar FTS5 para nomes, logradouros e atividade. | Tempo p50/p95 de filtros e sugestões com 2 mil e 70 mil registros. |
| Resolvida | `backend/projects.py`, `list`: cada projeto relia prontidão e listas de jobs. | Compartilhar o snapshot por requisição. | Contagem de chamadas caiu para uma de cada tipo com 20 projetos de teste. |

## Segurança: prioridades

| Prioridade | Situação | Ação |
| --- | --- | --- |
| Alta | A interface ainda usa `innerHTML` e handlers inline. Os identificadores do Acervo agora são serializados e escapados, mas outras telas requerem auditoria de cada interpolação. | Substituir por `textContent`/nós DOM e eventos delegados. Criar teste com `<`, `>`, `&` e aspas em todos os campos importáveis. |
| Aplicada | Um middleware ASGI limita o corpo do upload durante a chegada, inclusive sem `Content-Length`. A cópia final continua limitada e remove arquivo parcial. | Testes HTTP cobrem upload em fluxo e resposta 413. |
| Alta | O motor GEO ainda carrega todo CSV/Parquet em pandas para deduplicação e geocodificação. | Planejar processamento em lotes com cache persistente e validação de equivalência de score, empates e coordenadas. |
| Média | Filtros, buscas, páginas e seleção estão limitados. A exportação completa ainda pode produzir resposta muito grande. | Medir e limitar duração/tamanho de exportações, com cancelamento e aviso ao usuário. |
| Resolvida | A aplicação local não verificava host nem origem de escritas; o motor GEO aceitava qualquer origem por CORS. | Host local, verificação de origem e CORS restrito. Testados com origem externa e host não local. |
| Resolvida | A rota de download do motor GEO montava o caminho a partir de parâmetros sem validar o job e o arquivo. | Validar ID, nome, diretório resolvido, arquivo regular e ausência de symlink. |

A proteção de origem reduz ataques vindos de páginas abertas no navegador. Ela não equivale a autenticação. Se o GeoCNPJ for exposto em rede ou publicado como serviço, adicione autenticação, autorização por projeto, TLS e limites de requisição antes disso.

## Próxima rodada de medição

Use um mês e municípios pequenos e grandes já autorizados para teste. Registre: partes e bytes lidos, linhas/s, duração por etapa, pico de memória, tamanho do resultado, tempo de abertura do mapa e latência p95 de filtros. Compare as mesmas entradas e formatos antes/depois de cada otimização. Preserve contagem de registros, CNPJ e coordenadas ao comparar resultados.

## Verificação desta rodada

- Foram acrescentados testes de upload HTTP sem `Content-Length`, junção de partes CSV/Parquet, escrita GeoJSON e leitura de arquivo maior que 4 MiB. A distribuição passou nos testes automatizados em Windows; a instalação limpa e as rotas HTTP foram conferidas separadamente.
- Os testes novos cobrem remoção de upload parcial, limites de filtros, prevenção de fórmula em CSV e preservação do valor no GeoJSON.
- A suíte usa dados pequenos e sintéticos. Ela não mede tempo ou memória com a base nacional e não substitui validação de equivalência em um mês completo.

## Medição sintética de leitura GeoJSON (23/11/2026)

Com `python scripts/benchmark_memory.py --records 20000`, o arquivo gerado tinha 5,6 MiB. O parser integral levou 0,551 s e atingiu 28,6 MiB de pico em alocações Python; a leitura em fluxo levou 1,296 s e atingiu 0,3 MiB. Portanto, nesta entrada a memória caiu, mas a leitura ficou mais lenta. Por isso arquivos de até 4 MiB continuam usando o parser integral. O teste mede somente a leitura JSON sintética com `tracemalloc`; não inclui SQLite, tiles, processamento nacional nem memória nativa do pandas.

A maior oportunidade de ganho no tempo de preparação municipal continua sendo evitar uma nova varredura de todos os ZIPs para cada município. Um índice mensal exige construção e espaço em disco; deve ser prototipado e comparado com dois ou mais municípios do mesmo mês antes de virar padrão.

## Limites para publicação

- O servidor é local e não oferece autenticação; mantenha a ligação em `127.0.0.1`.
- O MapLibre é carregado de uma URL fixa com hash SHA-384; os tiles do OpenStreetMap ainda dependem da internet.
- As dependências diretas estão fixadas, mas as transitivas podem mudar na primeira instalação. Uma trava completa de dependências pode ser adicionada após validação em Windows, macOS e Linux.
- A distribuição não inclui dados oficiais ou resultados de usuários.
