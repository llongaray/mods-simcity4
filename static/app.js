/* SimCity 2013 Mod Control — no external frontend libraries */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const palette = ['#48dbed','#4adea9','#ac92fb','#f5c779','#f68c9b','#5a93fa','#a9d78a','#76becf'];
  let snapshot = null;
  let fileMod = null;
  let activeFilter = 'todos';
  let busy = new Set();

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, char =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  }
  function bytes(n) {
    if (!n) return '0 KB';
    const units = ['B','KB','MB','GB'];
    let k = 0;
    while (n >= 1024 && k < units.length - 1) { n /= 1024; k++; }
    return n.toLocaleString('pt-BR',{maximumFractionDigits:k ? 1 : 0}) + ' ' + units[k];
  }
  function stamp() {
    return new Date().toLocaleTimeString('pt-BR',{hour12:false});
  }
  function term(message, error = false) {
    const el = $('terminal');
    const line = document.createElement('div');
    line.innerHTML = '<span class="term-time">' + esc(stamp()) + '</span> ' +
      '<span class="' + (error ? 'term-error' : 'term-accent') + '">SC13</span> ' + esc(message);
    el.appendChild(line);
    while (el.children.length > 45) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
  }
  let toastTimer;
  function toast(message, error = false) {
    const el = $('toast');
    el.textContent = message;
    el.classList.toggle('error', error);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 6000);
  }
  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrf;
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await fetch(path, Object.assign({}, options,{headers}));
    } catch (e) {
      throw new Error('Falha de conexão com o Flask: ' + e.message);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Erro HTTP ' + response.status);
    return data;
  }
  async function reload() {
    try {
      snapshot = await api('/api/summary');
      render(snapshot);
      $('last-updated').textContent = 'Atualizado às ' + stamp();
    } catch (e) {
      term(e.message,true);
      toast(e.message,true);
    }
  }
  function render(data) {
    $('side-state').textContent = data.ready ? 'Jogo localizado · pronto' : 'Configure a pasta do jogo';
    $('kpi-files').textContent = data.kpi.files.toLocaleString('pt-BR');
    $('kpi-catalog').textContent = data.kpi.catalog_installed;
    $('kpi-total').textContent = ' / ' + data.kpi.catalog_total;
    $('kpi-managed').textContent = data.kpi.managed;
    $('kpi-size').textContent = bytes(data.kpi.bytes);
    $('mods-count').textContent = data.mods.length + ' opções';
    $('inventory-count').textContent = data.inventory.length + ' arquivos';
    if (document.activeElement !== $('game-path')) $('game-path').value = data.game_path || '';
    $('config-hint').textContent = data.ready ?
      'Instalação detectada. Destino padrão: ' + data.targets.SimCityData :
      'Jogo ainda não detectado. Após a instalação, indique a pasta que contém SimCityData.';
    renderCatalog();
    renderInventory();
    drawCharts();
  }
  function renderCatalog() {
    if (!snapshot) return;
    const query = $('search').value.trim().toLocaleLowerCase('pt-BR');
    const filter = $('filter').value;
    const entries = snapshot.mods.filter(m => {
      const searchText = [m.name,m.description,m.category].concat(m.tags || []).join(' ').toLocaleLowerCase('pt-BR');
      return (!query || searchText.includes(query)) &&
        (filter === 'todos' || (filter === 'instalado' && m.installed) ||
         (filter === 'pendente' && !m.installed) || (filter === 'baixo' && m.level === 'baixo'));
    });
    const html = entries.map(m => {
      const stateLabel = m.installed ? 'Detectado' : 'Não detectado';
      const level = m.level === 'baixo' ? 'Baixo risco' : m.level === 'alto' ? 'Risco alto' : 'Atenção';
      const riskClass = m.level === 'alto' ? ' risk-high' : m.level === 'baixo' ? ' risk-low' : '';
      const opts = m.managed ?
        '<button class="button button-outline" data-act="remove" data-id="' + esc(m.id) + '">Desinstalar</button>' :
        m.installed ? '<button class="button button-outline" disabled>Já detectado</button>' :
        m.complex ?
        '<button class="button button-outline" data-act="instructions" data-id="' + esc(m.id) + '">Ver instruções</button>' :
        '<button class="button button-primary" data-act="download" data-id="' + esc(m.id) +
        '"' + (busy.has(m.id) ? ' disabled' : '') + '>' +
        (busy.has(m.id) ? 'Processando…' : 'Baixar e instalar') + '</button>' +
        '<button class="button button-ghost" data-act="import" data-id="' + esc(m.id) +
        '"' + (!snapshot.ready ? ' disabled title="Configure o jogo primeiro"' : '') + '>Importar</button>';
      const actions = opts + '<a href="' + esc(m.source) + '" target="_blank" rel="noopener noreferrer" title="Página do autor">↗</a>';
      return '<article class="mod-card">' +
        '<div class="mod-head"><span class="category-tag">' + esc(m.category) + '</span>' +
        '<span class="status-tag' + (m.installed ? ' installed' : '') + '">' + esc(stateLabel) + '</span></div>' +
        '<h3>' + esc(m.name) + '</h3><p class="mod-description">' + esc(m.description) + '</p>' +
        '<div class="mod-meta"><span class="mini-tag' + riskClass + '">' + esc(level) + '</span>' +
        (m.cot ? '<span class="mini-tag">Requer CoT</span>' : '') +
        (m.tags || []).slice(0,2).map(t => '<span class="mini-tag">' + esc(t) + '</span>').join('') +
        '</div><div class="mod-warning">' + esc(m.warning || '') + '</div><div class="mod-actions">' +
        actions + '</div></article>';
    }).join('');
    $('catalog-grid').innerHTML = html || '<div class="panel" style="padding:25px">Nenhum mod corresponde à pesquisa.</div>';
  }
  function renderInventory() {
    const list = snapshot.inventory;
    $('inventory-body').innerHTML = list.map(file =>
      '<tr><td>' + esc(file.name) + '</td><td>' + esc(file.path) + '</td>' +
      '<td><span class="inventory-badge">' + esc(file.category) + '</span></td>' +
      '<td>' + bytes(file.bytes) + '</td><td>' + (file.managed ? 'Gerenciador' : 'Instalação externa') + '</td></tr>'
    ).join('') || '<tr><td class="empty-row" colspan="5">Nenhum mod identificado nessa instalação. Arquivos originais do jogo são ocultados.</td></tr>';
  }
  function prepCanvas(canvas, targetW, targetH) {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(targetW * ratio);
    canvas.height = Math.round(targetH * ratio);
    canvas.style.width = targetW + 'px';
    canvas.style.height = targetH + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio,0,0,ratio,0,0);
    return ctx;
  }
  function drawCharts() {
    if (!snapshot) return;
    const entries = Object.entries(snapshot.categories).sort((a,b) => b[1]-a[1]);
    const canvas = $('donut');
    const ctx = prepCanvas(canvas, 200, 200);
    const total = entries.reduce((n,p) => n+p[1],0);
    let start = -Math.PI / 2;
    if (!total) {
      ctx.beginPath();ctx.arc(100,100,72,0,Math.PI*2);ctx.strokeStyle='#263b51';ctx.lineWidth=17;ctx.stroke();
    } else {
      entries.forEach((entry,i) => {
        const angle = 2*Math.PI*entry[1]/total;
        ctx.beginPath();ctx.arc(100,100,72,start,start+angle);ctx.strokeStyle=palette[i%palette.length];
        ctx.lineWidth=17;ctx.lineCap='butt';ctx.stroke();start+=angle;
      });
    }
    ctx.fillStyle = '#f0f6ff';ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='bold 32px Segoe UI';
    ctx.fillText(String(total),100,92);ctx.fillStyle='#889db4';ctx.font='11px Segoe UI';ctx.fillText('PACOTES',100,117);
    $('chart-legend').innerHTML = (entries.length ? entries : [['Nenhum mod',0]]).slice(0,7).map((entry,i) =>
      '<div class="legend-item"><span class="swatch" style="background:' + esc(palette[i%palette.length]) + '"></span>' +
      '<span>' + esc(entry[0]) + '</span><span class="number">' + entry[1] + '</span></div>').join('');
    const bar = $('bars');
    const width = Math.max(230,bar.parentElement.clientWidth-48);
    const h = 216;
    const bctx = prepCanvas(bar,width,h);
    const data = entries.slice(0,6);
    if (!data.length) {
      bctx.fillStyle='#91a7bb';bctx.font='13px Segoe UI';bctx.textAlign='center';
      bctx.fillText('Sem arquivos para analisar',width/2,100);
      return;
    }
    const max = Math.max(1,...data.map(x=>x[1]));
    data.forEach((entry,i) => {
      const y = 12+i*34;
      bctx.fillStyle='#95a9be';bctx.font='11px Segoe UI';bctx.textAlign='left';
      bctx.fillText(entry[0].slice(0,18),8,y+9);
      const x = Math.min(160,width*.40), w=width-x-38;
      bctx.fillStyle='#223448';bctx.fillRect(x,y,Math.max(w,8),10);
      const grad=bctx.createLinearGradient(x,0,x+w,0);
      grad.addColorStop(0,palette[i%palette.length]);grad.addColorStop(1,'#335d86');
      bctx.fillStyle=grad;bctx.fillRect(x,y,Math.max(4,w*entry[1]/max),10);
      bctx.fillStyle='#dceefa';bctx.textAlign='right';bctx.fillText(String(entry[1]),width-5,y+9);
    });
  }
  async function savePath() {
    const path = $('game-path').value.trim();
    try {
      const result = await api('/api/config',{method:'POST',body:JSON.stringify({game_path:path})});
      term('Pasta do jogo configurada: '+result.game_path);
      toast('Instalação localizada com sucesso.');
      await reload();
    } catch(e) {term(e.message,true);toast(e.message,true);}
  }
  async function importFile(id) {
    if (!snapshot || !snapshot.ready) return toast('Configure primeiro o diretório do jogo.',true);
    fileMod=id;
    $('upload-picker').value='';
    $('upload-picker').click();
  }
  async function uploadChosen(file) {
    if (!file || !fileMod) return;
    const id=fileMod;
    if (busy.has(id)) return;
    const form=new FormData();
    form.append('file',file,file.name);
    busy.add(id);renderCatalog();term('Validando arquivo local: '+file.name);
    try {
      const response=await api('/api/install/'+encodeURIComponent(id)+'/upload',{method:'POST',body:form});
      const installed=response.result.installed;
      term('Instalação finalizada: '+installed+' arquivo(s).');
      toast('Mod instalado! '+installed+' pacote(s) adicionado(s).');
      await reload();
    } catch(e) {
      term('Falha na importação: '+e.message,true);
      toast(e.message,true);
    } finally {busy.delete(id);renderCatalog();fileMod=null;}
  }
  async function startDownload(id) {
    if (!snapshot || !snapshot.ready) {toast('Configure primeiro a pasta do SimCity 2013.',true);document.getElementById('configuracao').scrollIntoView();return;}
    if (busy.has(id)) return;
    const mod=snapshot.mods.find(m=>m.id===id);
    busy.add(id);renderCatalog();term('Iniciando download: '+(mod ? mod.name : id));
    try {
      const answer=await api('/api/install/'+encodeURIComponent(id)+'/download',{method:'POST'});
      for (let step=0;step<120;step++) {
        await new Promise(resolve=>setTimeout(resolve,900));
        const job=await api('/api/jobs/'+encodeURIComponent(answer.job_id));
        if (job.status==='done') {
          term('Concluído: '+job.name+' ('+(job.result ? job.result.installed : 0)+' arquivo[s])');
          toast('Download e instalação concluídos.');
          await reload();
          return;
        }
        if (job.status==='manual'||job.status==='failed') {
          term('Download automático indisponível: '+job.message,true);
          toast('Fonte exige etapa manual. Abra ↗ na ficha do mod e depois clique Importar.',true);
          return;
        }
      }
      term('Download ainda em andamento; consulte o terminal Flask.');
      toast('A operação continua no servidor; atualize a página depois.');
    } catch(e) {
      term(e.message,true);
      toast(e.message,true);
    } finally {
      busy.delete(id);renderCatalog();
    }
  }
  async function removeManaged(id) {
    const mod=snapshot && snapshot.mods.find(m=>m.id===id);
    if (!mod || !mod.managed) return;
    if (!window.confirm('Remover os arquivos gerenciados de "'+mod.name+'"? Suas cidades não serão alteradas.')) return;
    try {
      const result=await api('/api/uninstall/'+encodeURIComponent(id),{method:'POST'});
      term('Removidos '+result.result.removed+' arquivos de '+mod.name);
      toast('Mod removido do jogo.');
      await reload();
    } catch(e) {term(e.message,true);toast(e.message,true);}
  }
  $('catalog-grid').addEventListener('click', event => {
    const button=event.target.closest('button[data-act]');
    if (!button || button.disabled) return;
    const id=button.dataset.id;
    if (button.dataset.act==='download') startDownload(id);
    if (button.dataset.act==='import') importFile(id);
    if (button.dataset.act==='remove') removeManaged(id);
    if (button.dataset.act==='instructions') {
      const mod=snapshot.mods.find(m=>m.id===id);
      if (mod) window.open(mod.source,'_blank','noopener,noreferrer');
    }
  });
  $('upload-picker').addEventListener('change',event=>uploadChosen(event.target.files[0]));
  $('save-path').addEventListener('click',savePath);
  $('game-path').addEventListener('keydown',event=>{if(event.key==='Enter')savePath();});
  $('search').addEventListener('input',renderCatalog);
  $('filter').addEventListener('change',renderCatalog);
  $('refresh').addEventListener('click',()=>{term('Executando nova leitura do diretório...');reload();});
  $('clear-log').addEventListener('click',()=>{$('terminal').textContent='';});
  window.addEventListener('resize',()=>{if(snapshot)drawCharts();});
  term('Painel conectado. Buscando diretório do SimCity 2013...');
  reload().then(()=>{if(snapshot&&!snapshot.ready)toast('Defina a pasta do jogo em Configurações.');});
})();
