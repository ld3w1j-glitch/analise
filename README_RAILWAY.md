# Versão para Railway

Esta versão foi preparada para publicar o Dashboard de Inventário Rotativo no Railway.

## Arquivos adicionados

- `Procfile`
- `railway.json`
- `runtime.txt`
- `.env.example`
- `gunicorn` no `requirements.txt`

## Variáveis recomendadas no Railway

Crie estas variáveis em **Variables**:

```text
INVENTARIO_SECRET_KEY=uma-chave-grande-e-dificil
```

Para manter os dados mesmo após redeploy, crie um **Volume** no Railway e configure:

```text
INVENTARIO_STORAGE_DIR=/data
```

Depois monte o volume no caminho `/data`.

## Login e registro

As telas de login e cadastro foram resumidas: agora aparecem apenas as janelas principais, sem blocos explicativos extras.

## Observação importante sobre uploads

Sem volume persistente, os dados podem ser perdidos em redeploy/rebuild. Para uso real, use o volume do Railway.
