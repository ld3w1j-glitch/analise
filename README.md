# Dashboard de Inventário Rotativo

Sistema em **Python + Flask** para importar planilhas de inventário rotativo e gerar dashboards visuais com histórico acumulado.

## Recursos principais

- Login por usuário;
- Cada usuário possui seus próprios arquivos, relatórios e histórico acumulado;
- Importação de `.xls`, `.xlsx` e `.xlsm`;
- Acúmulo de meses de diferentes planilhas;
- Se um mês já existir, o arquivo mais recente atualiza aquele mês sem duplicar;
- Dashboard com páginas separadas: Resumo Geral, Divergências e Detalhes & Exportação;
- Tooltips ao passar o mouse;
- Painel de detalhes ao clicar em gráficos, cards, ranking e tabela;
- Exportação CSV/JSON;
- Preparado para gerar `.exe` com ícone personalizado.

## Separação por usuário

Ao criar um usuário, o programa salva os dados em pastas separadas:

```text
data/usuarios/<usuario>/inventario_acumulado.json
uploads/usuarios/<usuario>/
reports/usuarios/<usuario>/
```

Isso evita que os arquivos de um usuário misturem com os arquivos de outro.

## Como rodar no Windows

Extraia o ZIP e execute:

```text
instalar_e_rodar.bat
```

Depois abra:

```text
http://127.0.0.1:5000
```

Na primeira vez, clique em **Criar cadastro** e crie o usuário.

## Como gerar o EXE

Execute:

```text
criar_exe_windows.bat
```

O executável será criado em:

```text
dist\InventarioDashboard\InventarioDashboard.exe
```

## Observação

O sistema salva os dados localmente no computador onde o programa está rodando. Se usar o EXE em outro computador, será um histórico diferente.
