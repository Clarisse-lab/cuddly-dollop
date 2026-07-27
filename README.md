# Dados Gov Plataforma

Fundação extensível para coletar e normalizar dados de APIs públicas. O núcleo conhece
apenas o contrato `PublicDataConnector`; cada fonte é um adaptador instalável e pode ser
adicionada sem editar os casos de uso, a persistência ou a CLI.

## Arquitetura

```text
CLI / futura API web
        |
    SyncService                 (orquestra paginação e retomada)
     /       \
Registry     RecordRepository   (portas do núcleo)
   |                |
connectores      SQLite         (adaptadores substituíveis)
   |
HttpClient -> urllib
```

Propriedades da base:

- descoberta de plugins via entry points `govdata.connectors`;
- paginação orientada por cursor e checkpoint transacional por página e parâmetros;
- reprocessamento idempotente por `(connector_id, dataset, external_id)`;
- proveniência por registro com URL da fonte e hash verificável do conteúdo;
- histórico imutável de versões distintas, sem duplicar coletas sem alteração;
- transporte HTTP, persistência e conectores injetáveis e testáveis offline;
- zero dependências de runtime no núcleo inicial.

## Uso rápido

Requer Python 3.11 ou mais recente.

```bash
python -m pip install -e .
govdata connectors
govdata sync ibge states
govdata sync ibge municipalities --param state=SP
govdata records ibge states
```

O banco padrão é `govdata.sqlite3`; use `--database caminho.sqlite3` antes do
subcomando para alterá-lo.

`--param CHAVE=VALOR` pode ser repetido e funciona sem escape especial no PowerShell.
O formato `--params '{"chave":"valor"}'` continua disponível em shells que preservam
as aspas JSON.

## API para o dashboard

Instale as dependências da API e dos testes:

```powershell
python -m pip install -e ".[api,test]"
```

Inicie o backend durante o desenvolvimento:

```powershell
govdata-api
```

A API ficará em `http://127.0.0.1:8000`, com documentação interativa em
`http://127.0.0.1:8000/docs`. Endpoints iniciais:

- `GET /health`
- `GET /api/v1/connectors`
- `GET /api/v1/records/{connector}/{dataset}?limit=50&offset=0`

O frontend permitido pode ser configurado sem alterar código:

```powershell
$env:GOVDATA_CORS_ORIGINS="https://seu-dashboard.netlify.app"
govdata-api
```

A API é somente de leitura. As sincronizações continuam no processo separado `govdata
sync`, evitando manter requisições HTTP abertas durante coletas longas.

## Dashboard web

O primeiro painel visual fica em `frontend/` e usa diretamente a API de leitura. Ele
apresenta indicadores consolidados, cobertura das fontes, distribuição territorial e
um explorador de oportunidades abertas do PNCP com busca e filtros.

Para testar localmente, mantenha a API em execução e sirva os arquivos estáticos:

```powershell
python -m http.server 5173 --directory frontend
```

Abra `http://127.0.0.1:5173`. A URL do backend fica em `frontend/config.js`; ela pode
apontar para a API local ou para o domínio público do Railway. Essa URL não é segredo.
Não abra `frontend/index.html` diretamente pelo Explorador de Arquivos: páginas
`file://` não têm uma origem web autorizável e o navegador bloqueia a leitura da API.

O `netlify.toml` publica diretamente a pasta `frontend`, sem etapa de build. Depois que
o Netlify gerar o domínio do painel, inclua essa origem exata na variável
`GOVDATA_CORS_ORIGINS` do serviço da API no Railway.

## PostgreSQL e migrations

SQLite continua sendo o padrão para desenvolvimento. Para produção, instale o adaptador
PostgreSQL junto com a API:

```powershell
python -m pip install -e ".[api,postgres]"
```

Configure a URL fornecida pela hospedagem e execute normalmente:

```powershell
$env:DATABASE_URL="postgresql://usuario:senha@servidor:5432/govdata"
govdata sync transparencia orgaos-siafi
govdata-api
```

`DATABASE_URL` seleciona automaticamente PostgreSQL para a CLI, o worker e a API. Sem
ela, a plataforma usa `govdata.sqlite3`. URLs `sqlite:///caminho.sqlite3` também são
aceitas.

As migrations SQL versionadas ficam em `src/govdata/infrastructure/migrations` e são
aplicadas automaticamente, uma única vez, ao iniciar o repositório. No PostgreSQL, uma
trava transacional evita concorrência entre instâncias durante a atualização do schema.

Não coloque `DATABASE_URL` no Git: ela normalmente contém a senha do banco e deve ser
configurada como secret na hospedagem do backend.

## Deploy do backend no Railway

O `Dockerfile` instala a API, o adaptador PostgreSQL e o plugin do Portal da
Transparência. O `railway.toml` configura o health check em `/health`; a porta pública
é fornecida pelo Railway e lida automaticamente pela aplicação.

1. No Railway, crie um projeto a partir deste repositório do GitHub.
2. Adicione um serviço PostgreSQL ao mesmo projeto.
3. No serviço da API, crie estas variáveis:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
PORTAL_TRANSPARENCIA_API_KEY=sua-chave-do-portal
GOVDATA_CORS_ORIGINS=https://seu-dashboard.netlify.app
```

O nome `Postgres` na referência deve ser igual ao nome do serviço de banco no projeto.
Se o Netlify também usar um domínio próprio, separe as origens permitidas por vírgula:

```text
GOVDATA_CORS_ORIGINS=https://seu-dashboard.netlify.app,https://dashboard.seudominio.com.br
```

Em **Settings > Networking**, gere um domínio público para a API. Depois do deploy,
confirme os endereços `https://seu-backend.up.railway.app/health` e
`https://seu-backend.up.railway.app/docs`.

No Netlify, configure apenas a URL pública do backend, por exemplo
`VITE_API_URL=https://seu-backend.up.railway.app`. A chave do Portal e a URL do banco
pertencem somente ao Railway e nunca devem ser expostas ao frontend.

### Sincronização em produção

A API é um serviço permanente e apenas lê os registros. Para atualizar os dados,
execute no serviço da API pelo shell do Railway:

```bash
govdata sync transparencia orgaos-siafi
```

Depois da primeira carga, pode ser criado um segundo serviço a partir da mesma imagem,
compartilhando `DATABASE_URL` e `PORTAL_TRANSPARENCIA_API_KEY`, com o comando acima e
um Cron Schedule. Esse processo termina ao concluir a coleta, como exigido pelos Cron
Jobs do Railway.

O arquivo `railway.worker.toml` já contém a configuração desse serviço. Para ativá-lo:

1. adicione outro serviço ao projeto apontando para o mesmo repositório GitHub;
2. nomeie o serviço como `transparencia-sync`;
3. em **Settings > Config-as-code**, selecione `/railway.worker.toml`;
4. adicione ao worker as variáveis abaixo;
5. não gere domínio público para o worker.

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
PORTAL_TRANSPARENCIA_API_KEY=sua-chave-do-portal
```

O worker executa `govdata sync transparencia orgaos-siafi` diariamente às 09:00 UTC,
equivalente a 06:00 no horário de Brasília. O agendamento pode ser alterado em
`cronSchedule`; cron jobs do Railway sempre usam UTC.

Para oportunidades abertas do PNCP, crie outro serviço sem domínio público e use
`/railway.pncp-worker.toml` em **Settings > Config-as-code**. Esse worker precisa apenas
da referência ao banco:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Ele executa `govdata sync pncp open-opportunities` a cada seis horas. A API pública do
PNCP não exige chave. O conector limita a paginação a 12 requisições por minuto e
aguarda automaticamente quando o serviço responde com HTTP 429 ou falhas temporárias
HTTP 500, 502, 503 e 504.

Para emendas parlamentares, crie um terceiro worker usando
`/railway.emendas-worker.toml`. Ele compartilha as mesmas variáveis do worker do Portal:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
PORTAL_TRANSPARENCIA_API_KEY=sua-chave-do-portal
```

O worker coleta diariamente as emendas do ano corrente às 10:00 UTC. Cargas históricas
podem ser executadas pontualmente com
`govdata sync transparencia emendas --param ano=2024`.

Para sanções e impedimentos, crie um worker usando
`/railway.sanctions-worker.toml` com as mesmas variáveis do Portal. Ele executa
`govdata sync-many transparencia ceis cnep cepim` diariamente às 02:00 UTC,
sincronizando os três cadastros em sequência no mesmo serviço.

## Criando um conector externo

Um pacote separado precisa apenas implementar o contrato estável:

```python
from govdata.core.models import ConnectorPage, ConnectorRecord, ConnectorSpec
from govdata.core.ports import PublicDataConnector

class MeuConnector(PublicDataConnector):
    spec = ConnectorSpec(
        id="minha-api",
        display_name="Minha API Pública",
        datasets=("recursos",),
    )

    async def fetch_page(self, dataset, parameters, cursor, http):
        response = await http.get("https://api.exemplo.gov.br/recursos")
        items = response.json()
        return ConnectorPage(
            records=tuple(
                ConnectorRecord(external_id=str(item["id"]), data=item)
                for item in items
            )
        )
```

E declarar no `pyproject.toml` do próprio plugin:

```toml
[project.entry-points."govdata.connectors"]
minha-api = "meu_plugin:MeuConnector"
```

Ao instalar esse pacote no mesmo ambiente, `govdata connectors` passa a encontrá-lo
automaticamente. Nenhum arquivo do núcleo precisa ser modificado.

## Plugin do Portal da Transparência

O primeiro plugin externo está em `plugins/govdata-transparencia` e coleta órgãos do
SIAFI com autenticação e paginação. Instale e use sem gravar a chave no repositório:

```powershell
python -m pip install -e .\plugins\govdata-transparencia
$env:PORTAL_TRANSPARENCIA_API_KEY="sua-chave"
govdata connectors
govdata sync transparencia orgaos-siafi
govdata sync transparencia emendas
govdata records transparencia orgaos-siafi
govdata records transparencia emendas --limit 10
```

Consulte o README do plugin para detalhes. A chave nunca deve ser enviada como argumento
de linha de comando ou incluída em arquivos versionados.

## Plugin do PNCP

O plugin em `plugins/govdata-pncp` consulta oportunidades com recebimento de propostas
aberto no Portal Nacional de Contratações Públicas:

```powershell
python -m pip install -e .\plugins\govdata-pncp
govdata sync pncp open-opportunities
govdata records pncp open-opportunities --limit 10
```

Filtros oficiais do PNCP, como UF, município, CNPJ e modalidade, podem ser enviados
com `--param`. Cada oportunidade guarda o identificador oficial, a URL de consulta,
a data de atualização da fonte e o histórico das mudanças do conteúdo.

## Plugin do Transferegov

O plugin em `plugins/govdata-transferegov` integra a API pública de Gestão de Parcerias
do Transferegov sem exigir chave:

```powershell
python -m pip install -e .\plugins\govdata-transferegov
govdata sync transferegov amendment-beneficiaries
govdata sync transferegov payment-documents
govdata sync transferegov payment-orders
```

`amendment-beneficiaries` traz CNPJ, município, UF, parlamentar, número da emenda e
valores. `payment-documents` traz o documento hábil com CNPJ e nome do credor,
parceria, valor e data. `payment-orders` traz ordens de pagamento e bancárias,
situação, datas e valor. Os datasets usam páginas de até 200 itens, limitação preventiva de
requisições e repetição automática para falhas temporárias.

Para produção, crie workers separados com
`/railway.transferegov-beneficiaries-worker.toml`,
`/railway.transferegov-payment-documents-worker.toml` e
`/railway.transferegov-payments-worker.toml`. Todos precisam somente de:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

As coletas são agendadas diariamente às 11:00, 11:30 e 12:00 UTC, respectivamente.

## Proveniência e histórico

`records` mantém a versão atual de cada registro para consultas rápidas. A tabela
`record_versions` preserva uma cópia somente quando o hash do conteúdo muda. Isso
permite reconstruir mudanças ao longo do tempo sem multiplicar versões idênticas.

A API retorna `source_url` e `content_hash` junto de cada registro. Esses campos serão
usados pelas futuras análises e respostas de IA para apresentar a evidência original.

## Cruzamento de dados entre fontes

Cada conector grava registros isolados por fonte. As tabelas `entities` e
`entity_links` (migration `004_entities.sql`) formam uma camada separada que liga
registros de fontes diferentes que se referem à mesma entidade do mundo real — o
primeiro passo concreto para transformar coleta em inteligência.

Rode a resolução depois de sincronizar os dados:

```bash
govdata link
```

O comando varre os datasets com regras de extração conhecidas
(`src/govdata/application/entity_resolution.py`) e grava vínculos idempotentes; rodar
várias vezes não duplica nada.

As gravações são agrupadas por página em uma única transação. A varredura continua
completa para preservar a mesma cobertura dos dados, mas evita abrir uma conexão e
uma transação para cada registro individual.

**Escopo desta primeira versão, de propósito:**

- Liga `pncp/open-opportunities`, `transferegov/amendment-beneficiaries`,
  `transferegov/payment-documents` e os cadastros `transparencia/ceis`,
  `transparencia/cnep` e `transparencia/cepim`, que possuem campos de CNPJ confirmados
  (`orgaoEntidade.cnpj`, `nr_cnpj_beneficiario_emenda` e `cd_credor_devedor`).
  O UF de `unidadeOrgao.ufSigla`
  do PNCP é extraído de forma tolerante (best-effort), já que só foi observado no
  frontend, não confirmado nos testes do conector.
- `transferegov/payment-orders` não contém CNPJ diretamente, mas é ligado pelo
  `id_documento_habil` ao documento de pagamento correspondente. CEIS, CNEP e CEPIM
  usam os campos oficiais de CNPJ do sancionado. `transparencia/emendas` continua fora
  até que exista um campo estruturado e confiável de vínculo.
- CPF (pessoa física) é ignorado deliberadamente: `nr_cnpj_beneficiario_emenda` só vira
  entidade quando tem exatamente 14 dígitos. Não constrói um grafo de pessoas físicas
  a partir de dados públicos.
- Cada execução refaz uma varredura completa dos datasets registrados (não é
  incremental). Aceitável para o volume atual; uma versão futura pode reaproveitar a
  tabela `checkpoints` com um cursor dedicado se os volumes crescerem muito.

Consulte o resultado pela API:

```text
GET /api/v1/entities/organization/{cnpj}
```

Retorna o nome conhecido da entidade e todos os registros de todas as fontes já
vinculados a ela (conector, dataset, id externo e o papel — `buyer`, `beneficiary` etc.).

Em produção, `railway.entity-resolution-worker.toml` roda `govdata link` diariamente
às 13:00 UTC, depois dos workers de sincronização. Ele quebra de propósito o padrão
1 cron : 1 (conector, dataset) dos outros workers, já que o cruzamento em si depende
de olhar mais de uma fonte na mesma execução.

## Desenvolvimento

Os testes usam apenas a biblioteca padrão:

```bash
python -m unittest discover -s tests -v
```
