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
govdata records transparencia orgaos-siafi
```

Consulte o README do plugin para detalhes. A chave nunca deve ser enviada como argumento
de linha de comando ou incluída em arquivos versionados.

## Desenvolvimento

Os testes usam apenas a biblioteca padrão:

```bash
python -m unittest discover -s tests -v
```
