# Conector PNCP

Plugin do Portal Nacional de Contratações Públicas para a plataforma GovData.

O dataset `open-opportunities` consulta contratações com recebimento de propostas
aberto. Sem `dataFinal`, o conector utiliza a data UTC da execução.

```powershell
python -m pip install -e .\plugins\govdata-pncp
govdata sync pncp open-opportunities
govdata records pncp open-opportunities --limit 10
```

Filtros oficiais podem ser enviados individualmente:

```powershell
govdata sync pncp open-opportunities --param uf=SP
```

O endpoint público de consulta do PNCP não exige chave.
