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

## Datasets

- `orgaos-siafi`: órgãos cadastrados no SIAFI, paginados pelo parâmetro oficial `pagina`.
- `emendas`: emendas parlamentares do ano corrente, com filtros opcionais de autor,
  função, UF e município. Para uma carga histórica, informe `--param ano=2024`.
- `ceis`: Cadastro Nacional de Empresas Inidôneas e Suspensas.
- `cnep`: Cadastro Nacional de Empresas Punidas.
- `cepim`: Entidades Privadas sem Fins Lucrativos Impedidas.

Exemplos:

```powershell
govdata sync transparencia emendas
govdata sync transparencia emendas --param ano=2024
govdata sync transparencia emendas --param ano=2025 --param nomeAutor="Nome do autor"
govdata records transparencia emendas --limit 10
govdata sync-many transparencia ceis cnep cepim
```

O catálogo `DATASETS` em `connector.py` permite acrescentar novos endpoints mantendo a
autenticação, paginação, limitação de chamadas e tratamento de erros compartilhados.
