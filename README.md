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

## Desenvolvimento

Os testes usam apenas a biblioteca padrão:

```bash
python -m unittest discover -s tests -v
```
