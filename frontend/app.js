const API_URL = (window.GOVDATA_CONFIG?.API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const state = { connectors: [], summaries: [], opportunities: [], opportunityTotal: 0 };
const elements = {
  apiStatus: document.querySelector("#api-status"),
  refreshButton: document.querySelector("#refresh-button"),
  lastUpdated: document.querySelector("#last-updated"),
  opportunitiesMetric: document.querySelector("#metric-opportunities"),
  connectorsMetric: document.querySelector("#metric-connectors"),
  datasetsMetric: document.querySelector("#metric-datasets"),
  recordsMetric: document.querySelector("#metric-records"),
  statesMetric: document.querySelector("#metric-states"),
  stateChart: document.querySelector("#state-chart"),
  stateSampleLabel: document.querySelector("#state-sample-label"),
  insightList: document.querySelector("#insight-list"),
  searchInput: document.querySelector("#search-input"),
  stateFilter: document.querySelector("#state-filter"),
  sortFilter: document.querySelector("#sort-filter"),
  resultCount: document.querySelector("#result-count"),
  sampleNotice: document.querySelector("#sample-notice"),
  opportunityTable: document.querySelector("#opportunity-table"),
  sourceGrid: document.querySelector("#source-grid"),
  apiDocsLink: document.querySelector("#api-docs-link"),
  toast: document.querySelector("#toast"),
};
const numberFormat = new Intl.NumberFormat("pt-BR");
const currencyFormat = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const dateFormat = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric" });

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function normalize(value) {
  return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}
function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch { return "#"; }
}
async function fetchJson(path) {
  const response = await fetch(`${API_URL}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`A API respondeu com status ${response.status}`);
  return response.json();
}
function setApiStatus(mode, message) {
  elements.apiStatus.className = `api-status ${mode}`;
  elements.apiStatus.querySelector("span:last-child").textContent = message;
}
function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.setTimeout(() => elements.toast.classList.remove("visible"), 3500);
}
function opportunityView(record) {
  const data = record.data || {};
  const unit = data.unidadeOrgao || {};
  const organization = data.orgaoEntidade || {};
  return {
    ...record,
    object: data.objetoCompra || data.informacaoComplementar || "Objeto não informado",
    organization: organization.razaoSocial || unit.nomeUnidade || "Órgão não informado",
    city: unit.municipioNome || "Município não informado",
    state: unit.ufSigla || "",
    modality: data.modalidadeNome || data.modoDisputaNome || "Modalidade não informada",
    value: Number(data.valorTotalEstimado) || 0,
    deadline: data.dataEncerramentoProposta || null,
    publishedAt: data.dataPublicacaoPncp || data.dataInclusao || record.source_updated_at,
  };
}
function renderMetrics() {
  const totalDatasets = state.connectors.reduce((total, item) => total + item.datasets.length, 0);
  const totalRecords = state.summaries.reduce((total, item) => total + (item.total || 0), 0);
  const states = new Set(state.opportunities.map((item) => item.state).filter(Boolean));
  elements.opportunitiesMetric.textContent = numberFormat.format(state.opportunityTotal);
  elements.connectorsMetric.textContent = numberFormat.format(state.connectors.length);
  elements.datasetsMetric.textContent = `${numberFormat.format(totalDatasets)} conjuntos de dados`;
  elements.recordsMetric.textContent = numberFormat.format(totalRecords);
  elements.statesMetric.textContent = numberFormat.format(states.size);
  const latest = state.opportunities.map((item) => new Date(item.collected_at)).filter((date) => !Number.isNaN(date.valueOf())).sort((a, b) => b - a)[0];
  elements.lastUpdated.textContent = latest ? `Última coleta: ${dateFormat.format(latest)}` : "Nenhuma coleta identificada";
}
function renderStateChart() {
  const totals = state.opportunities.reduce((result, item) => {
    const key = item.state || "N/I";
    result[key] = (result[key] || 0) + 1;
    return result;
  }, {});
  const ranking = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 7);
  if (!ranking.length) {
    elements.stateChart.innerHTML = '<p class="empty-state">Sem dados territoriais na amostra.</p>';
    return;
  }
  const maximum = ranking[0][1];
  elements.stateChart.innerHTML = ranking.map(([uf, count]) => `
    <div class="bar-row"><span>${escapeHtml(uf)}</span><div class="bar-track"><div class="bar-fill" style="width:${(count / maximum) * 100}%"></div></div><span>${numberFormat.format(count)}</span></div>
  `).join("");
  elements.stateSampleLabel.textContent = `${numberFormat.format(state.opportunities.length)} registros analisados`;
}
function renderInsights() {
  const valued = state.opportunities.filter((item) => item.value > 0);
  const totalValue = valued.reduce((total, item) => total + item.value, 0);
  const highest = [...valued].sort((a, b) => b.value - a.value)[0];
  const organizations = new Set(state.opportunities.map((item) => item.organization).filter(Boolean));
  const insights = [
    { title: valued.length ? currencyFormat.format(totalValue) : "Valor não disponível", description: "Soma estimada das oportunidades com valor informado na amostra." },
    { title: `${numberFormat.format(organizations.size)} órgãos compradores`, description: "Entidades distintas encontradas nos registros carregados." },
    { title: highest ? currencyFormat.format(highest.value) : "Sem valor informado", description: highest ? `Maior oportunidade da amostra: ${highest.organization}.` : "Ainda não há uma oportunidade valorada para destacar." },
  ];
  elements.insightList.innerHTML = insights.map((item, index) => `
    <div class="insight-item"><span class="insight-number">0${index + 1}</span><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.description)}</p></div></div>
  `).join("");
}
function populateStateFilter() {
  const current = elements.stateFilter.value;
  const states = [...new Set(state.opportunities.map((item) => item.state).filter(Boolean))].sort();
  elements.stateFilter.innerHTML = ['<option value="">Todas</option>', ...states.map((uf) => `<option value="${escapeHtml(uf)}">${escapeHtml(uf)}</option>`)].join("");
  elements.stateFilter.value = states.includes(current) ? current : "";
}
function filteredOpportunities() {
  const term = normalize(elements.searchInput.value);
  const selectedState = elements.stateFilter.value;
  return state.opportunities.filter((item) => {
    const searchable = normalize(`${item.object} ${item.organization} ${item.city} ${item.state} ${item.modality}`);
    return (!term || searchable.includes(term)) && (!selectedState || item.state === selectedState);
  }).sort((a, b) => {
    if (elements.sortFilter.value === "value-desc") return b.value - a.value;
    if (elements.sortFilter.value === "deadline") return new Date(a.deadline || "2999-12-31") - new Date(b.deadline || "2999-12-31");
    return new Date(b.publishedAt || 0) - new Date(a.publishedAt || 0);
  });
}
function renderOpportunities() {
  const records = filteredOpportunities();
  elements.resultCount.textContent = `${numberFormat.format(records.length)} oportunidades encontradas na amostra`;
  elements.sampleNotice.textContent = state.opportunityTotal > state.opportunities.length ? `Exibindo uma amostra de ${numberFormat.format(state.opportunities.length)} de ${numberFormat.format(state.opportunityTotal)} registros` : "";
  if (!records.length) {
    elements.opportunityTable.innerHTML = '<tr><td colspan="5" class="empty-state">Nenhuma oportunidade corresponde aos filtros.</td></tr>';
    return;
  }
  elements.opportunityTable.innerHTML = records.slice(0, 50).map((item) => {
    const deadline = item.deadline ? dateFormat.format(new Date(item.deadline)) : "Não informado";
    const sourceUrl = safeUrl(item.source_url);
    return `<tr>
      <td><span class="opportunity-title">${escapeHtml(item.object)}</span><span class="opportunity-meta">${escapeHtml(item.modality)} · ${escapeHtml(item.external_id)}</span></td>
      <td><strong>${escapeHtml(item.organization)}</strong><span class="location">${escapeHtml(item.city)}${item.state ? ` · ${escapeHtml(item.state)}` : ""}</span></td>
      <td><span class="value">${item.value ? escapeHtml(currencyFormat.format(item.value)) : "Não informado"}</span></td>
      <td><span class="deadline">${escapeHtml(deadline)}</span></td>
      <td>${sourceUrl === "#" ? "" : `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer" aria-label="Abrir fonte oficial">↗</a>`}</td>
    </tr>`;
  }).join("");
}
function renderSources() {
  if (!state.connectors.length) {
    elements.sourceGrid.innerHTML = '<p class="empty-state">Nenhuma fonte conectada.</p>';
    return;
  }
  elements.sourceGrid.innerHTML = state.connectors.map((connector) => {
    const records = state.summaries.filter((item) => item.connectorId === connector.id).reduce((total, item) => total + item.total, 0);
    return `<article class="source-card">
      <div class="source-card-top"><span class="source-initials">${escapeHtml(connector.id.toUpperCase().slice(0, 4))}</span><span class="source-live">Conectada</span></div>
      <h3>${escapeHtml(connector.name)}</h3>
      <p>${connector.datasets.length} ${connector.datasets.length === 1 ? "conjunto disponível" : "conjuntos disponíveis"}</p>
      <span class="source-count">${numberFormat.format(records)} registros</span>
    </article>`;
  }).join("");
}
async function loadDashboard() {
  elements.refreshButton.classList.add("loading");
  elements.refreshButton.disabled = true;
  setApiStatus("", "Conectando à API");
  if (window.location.protocol === "file:") {
    const localMessage = "Abra o painel por http://127.0.0.1:5173; o navegador bloqueia APIs em páginas abertas como arquivo.";
    setApiStatus("error", "Abra pelo servidor local");
    elements.opportunityTable.innerHTML = `<tr><td colspan="5" class="empty-state">${localMessage}</td></tr>`;
    elements.stateChart.innerHTML = `<p class="empty-state">${localMessage}</p>`;
    elements.insightList.innerHTML = `<p class="empty-state">${localMessage}</p>`;
    elements.sourceGrid.innerHTML = `<p class="empty-state">${localMessage}</p>`;
    showToast(localMessage);
    elements.refreshButton.classList.remove("loading");
    elements.refreshButton.disabled = false;
    return;
  }
  try {
    const [health, connectors] = await Promise.all([fetchJson("/health"), fetchJson("/api/v1/connectors")]);
    state.connectors = connectors;
    const summaryRequests = connectors.flatMap((connector) => connector.datasets.map(async (dataset) => {
      const page = await fetchJson(`/api/v1/records/${encodeURIComponent(connector.id)}/${encodeURIComponent(dataset)}?limit=1`);
      return { connectorId: connector.id, dataset, total: page.total };
    }));
    const summaryResults = await Promise.allSettled(summaryRequests);
    state.summaries = summaryResults.filter((result) => result.status === "fulfilled").map((result) => result.value);
    const pncpPage = await fetchJson("/api/v1/records/pncp/open-opportunities?limit=200");
    state.opportunityTotal = pncpPage.total;
    state.opportunities = pncpPage.items.map(opportunityView);
    setApiStatus("online", `API online · v${health.version}`);
    renderMetrics();
    renderStateChart();
    renderInsights();
    populateStateFilter();
    renderOpportunities();
    renderSources();
    showToast("Dashboard atualizado com os dados mais recentes.");
  } catch (error) {
    setApiStatus("error", "API indisponível");
    elements.opportunityTable.innerHTML = '<tr><td colspan="5" class="empty-state">Não foi possível carregar a API. Verifique a conexão e o CORS do Railway.</td></tr>';
    elements.stateChart.innerHTML = '<p class="empty-state">Dados indisponíveis.</p>';
    elements.insightList.innerHTML = '<p class="empty-state">Dados indisponíveis.</p>';
    elements.sourceGrid.innerHTML = '<p class="empty-state">Fontes indisponíveis.</p>';
    showToast(error.message || "Falha ao carregar o dashboard.");
  } finally {
    elements.refreshButton.classList.remove("loading");
    elements.refreshButton.disabled = false;
  }
}
elements.searchInput.addEventListener("input", renderOpportunities);
elements.stateFilter.addEventListener("change", renderOpportunities);
elements.sortFilter.addEventListener("change", renderOpportunities);
elements.refreshButton.addEventListener("click", loadDashboard);
elements.apiDocsLink.href = `${API_URL}/docs`;
loadDashboard();
