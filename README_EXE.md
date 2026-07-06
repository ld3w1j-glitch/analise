# Como criar o EXE no Windows

Esta versão está preparada para gerar o executável com PyInstaller e inclui:

- correção do erro do `launcher.py`;
- ícone personalizado no `.exe`;
- login por usuário;
- histórico acumulado separado para cada usuário.

## Ícone do EXE

O executável está configurado para usar:

```text
app_icon.ico
```

## Passo a passo para gerar o EXE

1. Extraia o ZIP em uma pasta do computador.
2. Abra a pasta extraída.
3. Dê dois cliques em:

```text
criar_exe_windows.bat
```

4. Aguarde o processo terminar.
5. O executável será criado em:

```text
dist\InventarioDashboard\InventarioDashboard.exe
```

## Antes de gerar novamente

Apague as pastas antigas, se existirem:

```text
build
dist
```

## Como usar depois que gerar

Dê dois cliques em:

```text
InventarioDashboard.exe
```

Ele abrirá o navegador automaticamente em:

```text
http://127.0.0.1:5000
```

Na primeira abertura, crie um usuário em **Criar cadastro**.

## Dados separados por usuário

Cada usuário terá suas próprias pastas de dados dentro da pasta do programa:

```text
data\usuarios\<usuario>\inventario_acumulado.json
uploads\usuarios\<usuario>\
reports\usuarios\<usuario>\
```

Assim, quando um usuário importar uma planilha, ela não mistura com o histórico dos outros usuários.

## Para levar para outro computador

Copie a pasta inteira:

```text
dist\InventarioDashboard
```

Não copie apenas o `.exe`, porque ele precisa dos arquivos internos para carregar templates, CSS, JavaScript, vídeo e bibliotecas.
