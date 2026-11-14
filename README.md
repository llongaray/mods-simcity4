# SimCity (2013) — Mod Control

Painel local de gerenciamento de **mods de SimCity (2013)**, com Python e Flask. Interface responsiva em largura total, KPIs, gráficos Canvas, inventário e catálogo comunitário com links dos autores.

**Exclusivo para SimCity (2013), chamado também de SimCity 5. Não utilize mods para SimCity 4 Deluxe Edition.** O nome deste repositório foi mantido para preservar o link original, mas seu conteúdo agora se dedica ao jogo de 2013.

## Executar no Windows

Abra o CMD ou PowerShell:

    git clone https://github.com/llongaray/mods-simcity4.git
    cd mods-simcity4
    iniciar.bat

O script cria um ambiente Python local, instala as dependências e inicia o servidor. Requer **Python 3.10+**. Abra **http://127.0.0.1:5000**.

Para executar manualmente:

    py -3 -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python app.py

Para atualizar um clone existente:

    git pull origin main
    iniciar.bat

## Localizar o jogo

O aplicativo não exige EA App, Steam ou outro launcher; aceita instalações locais com a estrutura real do SimCity 2013.

1. Instale e abra o jogo ao menos uma vez, preferencialmente em modo offline.
2. **Feche o jogo** antes de adicionar ou remover mods.
3. Em **Configurações**, indique a pasta raiz que contém SimCityData, por exemplo: E:\Jogos\SimCity 2013
4. O sistema detectará arquivos .package do jogo, salvará a configuração e analisará os mods.

Também é possível definir a variável de ambiente SIMCITY_PATH. A variável tem prioridade sobre o caminho salvo na interface. **Nunca use o diretório do SimCity 4.**

O aplicativo **não altera executáveis, não remove proteções, não distribui cracks e não modifica DRM**. A compatibilidade com builds/repack específicos não é garantida sem teste local.

## Instalar mods

### Botão “Baixar e instalar”

O gerenciador tenta baixar arquivos a partir da fonte original do Simtropolis. Quando recebe conteúdo válido, extrai os pacotes .package e instala os arquivos permitidos no destino correspondente. O terminal Flask e a interface informam o resultado.

**O Simtropolis pode exigir login, permitir múltiplos arquivos ou impor limites de download.** Nesses casos, a instalação automática **não é concluída** e isso é informado explicitamente. Clique no link ↗ da ficha do mod, baixe o arquivo diretamente no site do autor e depois use **Importar** no painel. Não há tentativa de contornar restrições do site.

São aceitos .package, .zip, .7z e .rar contendo pacotes DBPF válidos. Para RAR, configure no Windows o 7-Zip ou backend de extração compatível com a biblioteca rarfile. O gerenciador nunca executa instaladores .exe ou scripts de terceiros.

### Caminhos de instalação

Para pacotes de dados simples:

    <pasta SimCity 2013>\SimCityData\

Certos mods exigem scripts adicionais:

    <pasta SimCity 2013>\SimCityUserData\Packages\

E alguns scripts originais são mantidos na pasta EcoGame. **Pacotes complexos e dependências de script não serão instalados automaticamente sem uma estratégia específica**, porque colocar tudo indiscriminadamente em SimCityData pode corromper a instalação. Consulte sempre o README de cada mod.

O gerenciador impede sobrescrever arquivos originais do jogo e também arquivos externos de mesmo nome.

### Inventário e desinstalação

- KPIs de pacotes externos, mods detectados no catálogo, gerenciados e armazenamento ocupado.
- Gráficos de categorias e quantidade de arquivos, alimentados pela varredura real.
- Inventário com nome do pacote, localização, categoria, tamanho e origem.
- Catálogo com popularidade, risco, requisitos, advertências e links.
- Remoção apenas dos arquivos instalados pelo gerenciador, após conferir SHA-256.
- Configuração e histórico persistidos na pasta .runtime, não publicada no Git.

A detecção de mods instalados externamente usa o **nome do arquivo**, e não inspeção integral da estrutura DBPF. Portanto, o status “Detectado” não comprova que o mod realmente funciona em seu build.

## Compatibilidade

- **Project Akar:** incompatibilidades documentadas com determinados addons de ruas.
- **Project Orion / Orion's Belt:** relatos de problemas; evitar instalação automática de pacotes complexos.
- **MagLev as Subway:** exige a expansão Cities of Tomorrow (CoT).
- **Danny's Camera Mod Pack:** selecionar somente uma câmera.
- **No Agent Clumping:** escolher variante conforme a presença de Extended Worker Data.
- **Twinzens 2020 Collection:** arquivos em pastas distintas; algumas combinações foram afetadas pela atualização de 2024.

Faça backup das cidades e regiões antes de experimentar mods que alteram a simulação.

## Fontes e créditos

Este repositório contém somente software gerenciador: os arquivos dos mods pertencem aos seus autores e **não são redistribuídos** aqui.

- [Simtropolis — SC13 Game Mods](https://community.simtropolis.com/files/category/19-sc13-game-mods/)
- [Simtropolis — SC13 User Interface](https://community.simtropolis.com/files/category/22-sc13-user-interface/)
- [Ultimate Mod Guide 2025+ (ativo em 2026)](https://community.simtropolis.com/forums/topic/763919-sc13-ultimate-mod-guide-2025/)
- [SimCityMods Wiki — Mod Installation](https://simcitymods.fandom.com/wiki/Mod_Installation)

A presença de um mod no catálogo não garante sua segurança ou compatibilidade.

## Testes

    python -m unittest discover -s tests -v

## Segurança

Servidor padrão limitado a 127.0.0.1:5000, proteção CSRF, limites para downloads externos, verificação de assinatura DBPF e do conteúdo dos arquivos compactados, destinos restritos ao diretório do jogo e controle por hash na desinstalação. Não exponha a porta 5000 publicamente.

Licença do código: AGPL-3.0 (consulte LICENSE).
