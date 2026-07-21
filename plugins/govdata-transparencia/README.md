# Conector Portal da Transparência

Plugin independente para a API de dados do Portal da Transparência do Governo Federal.

## Instalação local

Na raiz do repositório:

```powershell
python -m pip install -e .\plugins\govdata-transparencia
```

Cadastre-se no Portal e defina a chave somente no processo atual do PowerShell:

```powershell
$env:PORTAL_TRANSPARENCIA_API_KEY="sua-chave"
govdata connectors
govdata sync transparencia orgaos-siafi
govdata records transparencia orgaos-siafi
```

A chave não deve ser colocada em arquivos versionados nem passada por argumento de CLI.

## Dataset inicial

- `orgaos-siafi`: órgãos cadastrados no SIAFI, paginados pelo parâmetro oficial `pagina`.

O catálogo `DATASETS` em `connector.py` permite acrescentar novos endpoints mantendo a
autenticação, paginação, limitação de chamadas e tratamento de erros compartilhados.
