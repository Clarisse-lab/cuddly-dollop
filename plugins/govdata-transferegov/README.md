# Conector Transferegov

Plugin para a API pública do módulo Gestão de Parcerias do Transferegov.

## Datasets

- `amendment-beneficiaries`: beneficiários de emendas, com CNPJ, município, UF,
  parlamentar, número e valores.
- `payment-orders`: ordens de pagamento e ordens bancárias, com situação, datas e
  valor pago.

## Uso local

```powershell
python -m pip install -e .\plugins\govdata-transferegov
govdata connectors
govdata sync transferegov amendment-beneficiaries
govdata sync transferegov payment-orders
govdata records transferegov amendment-beneficiaries --limit 10
```

A API é pública e não exige chave. Filtros oficiais adicionais podem ser enviados com
`--param CHAVE=VALOR`; paginação e tamanho de página são controlados pelo conector.
