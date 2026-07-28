# Conector PNCP

Plugin do Portal Nacional de Contratações Públicas para a plataforma GovData.

O dataset `open-opportunities` consulta contratações com recebimento de propostas
aberto. O dataset `contracts` consulta contratos e empenhos pela data de atualização
global. Sem datas explícitas, contratos usam o dia UTC anterior à execução.

```powershell
python -m pip install -e .\plugins\govdata-pncp
govdata sync pncp open-opportunities
govdata sync pncp contracts
govdata records pncp open-opportunities --limit 10
govdata records pncp contracts --limit 10
```

Filtros oficiais podem ser enviados individualmente:

```powershell
govdata sync pncp open-opportunities --param uf=SP
govdata sync pncp contracts --param dataInicial=20260101 --param dataFinal=20261231
```

O endpoint público de consulta do PNCP não exige chave.

Por padrão, o conector limita a coleta a 12 requisições por minuto e aplica espera
exponencial quando a API responde com HTTP 429 ou com falhas temporárias 5xx. A
cadência pode ser alterada com a configuração `requests_per_minute`, mas valores
maiores podem provocar bloqueio temporário pelo PNCP.
