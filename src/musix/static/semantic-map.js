(() => {
  "use strict";

  const mapElement = document.querySelector("#semantic-map");
  if (!mapElement || !window.cytoscape) return;

  const status = document.querySelector("#map-status");
  const root = document.documentElement;
  const themeSelect = document.querySelector("#theme-select");
  const query = document.querySelector("#query");
  const graphUrl = mapElement.dataset.graphUrl;
  const preferredDark = window.matchMedia("(prefers-color-scheme: dark)");
  let currentLod = -1;

  const say = (message) => {
    if (status) status.textContent = message;
  };

  const setTheme = (value) => {
    const mode = value === "system" ? (preferredDark.matches ? "dark" : "light") : value;
    root.dataset.theme = mode;
    if (themeSelect) themeSelect.value = value;
    window.localStorage.setItem("musix-theme", value);
  };

  const storedTheme = window.localStorage.getItem("musix-theme") || "system";
  setTheme(storedTheme);
  themeSelect?.addEventListener("change", () => setTheme(themeSelect.value));
  preferredDark.addEventListener("change", () => {
    if ((window.localStorage.getItem("musix-theme") || "system") === "system") setTheme("system");
  });

  const nodeId = (raw) => `genre-${raw.genre_id ?? raw.id}`;
  const getNodes = (payload) => payload.nodes ?? payload.graph?.nodes ?? payload.points ?? [];
  const getEdges = (payload) => payload.edges ?? payload.graph?.edges ?? [];
  const getLods = (payload) => payload.lods ?? payload.graph?.lods ?? [];

  const normalisedPositions = (nodes) => {
    const xs = nodes.map((node) => Number(node.x)).filter(Number.isFinite);
    const ys = nodes.map((node) => Number(node.y)).filter(Number.isFinite);
    const minX = Math.min(...xs, 0); const maxX = Math.max(...xs, 1);
    const minY = Math.min(...ys, 0); const maxY = Math.max(...ys, 1);
    const spanX = Math.max(maxX - minX, 0.0001); const spanY = Math.max(maxY - minY, 0.0001);
    return new Map(nodes.map((node) => [nodeId(node), {
      x: 180 + ((Number(node.x) - minX) / spanX) * 2200,
      y: 160 + ((Number(node.y) - minY) / spanY) * 1500,
    }]));
  };

  const elementsFor = (payload) => {
    const nodes = getNodes(payload);
    const positions = normalisedPositions(nodes);
    const elements = nodes.map((node) => {
      const id = nodeId(node);
      const parentId = node.display_parent_id;
      return {
        data: {
          id,
          genreId: node.genre_id ?? node.id,
          label: node.name,
          detailHref: node.detail_href ?? null,
          parent: parentId === null || parentId === undefined ? undefined : `genre-${parentId}`,
          depth: node.depth ?? 1,
          // Legacy point responses have no semantic tiers; keep them usable while
          // production-map-v1 supplies its explicit `lod_min` contract.
          lodMin: node.lod_min ?? 0,
          weight: node.display_weight ?? node.weight ?? 0,
          displayLabel: "",
          subtreeSize: node.subtree_size ?? 0,
          communityId: node.community_id ?? "",
        },
        position: positions.get(id),
        classes: parentId === null || parentId === undefined ? "umbrella" : "genre",
      };
    });
    for (const edge of getEdges(payload)) {
      const kind = edge.kind ?? "similarity";
      const source = `genre-${edge.source_genre_id ?? edge.source}`;
      const target = `genre-${edge.target_genre_id ?? edge.target}`;
      elements.push({ data: { id: `${kind}-${source}-${target}`, source, target, kind, weight: edge.weight ?? 0 }, classes: kind });
    }
    return elements;
  };

  const cssValue = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  const stylesheet = () => [
    { selector: "node", style: { "background-color": cssValue("--node"), label: "data(displayLabel)", color: cssValue("--ink"), "font-size": 13, "text-outline-color": cssValue("--canvas"), "text-outline-width": 3, "text-valign": "bottom", "text-margin-y": 7, width: 13, height: 13, "overlay-opacity": 0 } },
    { selector: "node.umbrella", style: { "background-color": cssValue("--parent"), width: 25, height: 25, "font-size": 16, "font-weight": 700, "border-width": 2, "border-color": cssValue("--node") } },
    { selector: ":parent", style: { "background-opacity": 0.12, "background-color": cssValue("--parent"), "border-width": 1, "border-color": cssValue("--node"), padding: 22, "text-valign": "top", "text-halign": "center" } },
    { selector: "node:selected", style: { "border-width": 4, "border-color": cssValue("--focus"), "background-color": cssValue("--focus") } },
    { selector: "edge", style: { width: 1, "line-color": cssValue("--edge"), opacity: 0.52, "curve-style": "straight" } },
    { selector: "edge.similarity", style: { "line-style": "dashed", "line-color": cssValue("--similarity"), opacity: 0.3 } },
    { selector: ".lod-hidden", style: { display: "none" } },
  ];

  const lodForZoom = (zoom) => zoom < 0.58 ? 0 : zoom < 0.95 ? 1 : zoom < 1.55 ? 2 : 3;
  const fallbackLabelIds = (cy, lod) => {
    const budget = [36, 72, 144, 320][lod];
    return new Set(cy.nodes().sort((left, right) => (
      Number(right.data("weight")) - Number(left.data("weight"))
      || String(left.data("label")).localeCompare(String(right.data("label")))
    )).slice(0, budget).map((node) => node.data("genreId")));
  };

  const updateLod = (cy, payload) => {
    const lod = lodForZoom(cy.zoom());
    if (lod === currentLod) return;
    currentLod = lod;
    const descriptor = getLods(payload).find((item) => Number(item.level) === lod);
    const visibleIds = new Set(descriptor?.visible_node_ids ?? cy.nodes().filter(
      (node) => Number(node.data("lodMin")) <= lod,
    ).map((node) => node.data("genreId")));
    const labels = mapElement.clientWidth <= 600 ? descriptor?.mobile_labels : descriptor?.desktop_labels;
    const labelIds = labels
      ? new Set(labels.filter((item) => item.shown).map((item) => item.genre_id))
      : fallbackLabelIds(cy, lod);
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const visible = visibleIds.has(node.data("genreId"));
        node.toggleClass("lod-hidden", !visible);
        node.data("displayLabel", visible && labelIds.has(node.data("genreId")) ? node.data("label") : "");
      });
      cy.edges().forEach((edge) => edge.toggleClass("lod-hidden", edge.source().hasClass("lod-hidden") || edge.target().hasClass("lod-hidden") || (edge.hasClass("similarity") && lod < 2)));
    });
    say(["Umbrella genres", "Genres", "Subgenres", "Detailed genres"][lod]);
  };

  const selectGenre = (cy, node) => {
    cy.$(":selected").unselect();
    node.select();
    const detailHref = node.data("detailHref");
    if (detailHref && window.htmx) {
      const link = document.createElement("a");
      link.href = detailHref;
      link.setAttribute("hx-get", detailHref);
      link.setAttribute("hx-target", "#genre-detail-slot");
      link.setAttribute("hx-swap", "innerHTML");
      link.setAttribute("hx-push-url", detailHref);
      link.hidden = true;
      document.body.append(link);
      window.htmx.process(link);
      link.click();
      window.setTimeout(() => link.remove(), 0);
      return;
    }
    const fallbackLink = document.querySelector(`#map-point-${node.data("genreId")}`);
    if (fallbackLink) fallbackLink.click();
  };

  fetch(graphUrl, { headers: { Accept: "application/json" } })
    .then((response) => response.ok ? response.json() : Promise.reject(new Error(`map request failed: ${response.status}`)))
    .then((payload) => {
      const nodes = getNodes(payload);
      if (!nodes.length) return;
      const cy = window.cytoscape({
        container: mapElement,
        elements: elementsFor(payload),
        style: stylesheet(),
        layout: { name: "preset", fit: true, padding: 72 },
        minZoom: 0.28,
        maxZoom: 4.8,
        userPanningEnabled: true,
        userZoomingEnabled: true,
        boxSelectionEnabled: false,
      });
      root.classList.add("js-map-ready");
      cy.resize();
      cy.fit(cy.elements(), 72);
      updateLod(cy, payload);
      cy.on("zoom", () => updateLod(cy, payload));
      cy.on("tap", "node", (event) => selectGenre(cy, event.target));
      cy.on("tap", (event) => { if (event.target === cy) cy.$(":selected").unselect(); });

      const selected = mapElement.dataset.selectedGenre;
      if (selected) cy.$(`#genre-${selected}`).select();
      document.querySelectorAll("[data-map-action]").forEach((button) => button.addEventListener("click", () => {
        const action = button.dataset.mapAction;
        if (action === "zoom-in") cy.zoom({ level: Math.min(cy.maxZoom(), cy.zoom() * 1.25), renderedPosition: { x: innerWidth / 2, y: innerHeight / 2 } });
        if (action === "zoom-out") cy.zoom({ level: Math.max(cy.minZoom(), cy.zoom() / 1.25), renderedPosition: { x: innerWidth / 2, y: innerHeight / 2 } });
        if (action === "fit") cy.fit(cy.elements(":visible"), 72);
      }));
      mapElement.addEventListener("keydown", (event) => {
        const key = event.key;
        if (["+", "=", "-", "_", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Escape"].includes(key)) event.preventDefault();
        if (key === "+" || key === "=") cy.zoom(cy.zoom() * 1.2);
        if (key === "-" || key === "_") cy.zoom(cy.zoom() / 1.2);
        if (key === "ArrowUp") cy.panBy({ x: 0, y: 60 });
        if (key === "ArrowDown") cy.panBy({ x: 0, y: -60 });
        if (key === "ArrowLeft") cy.panBy({ x: 60, y: 0 });
        if (key === "ArrowRight") cy.panBy({ x: -60, y: 0 });
        if (key === "Escape") cy.$(":selected").unselect();
      });
      mapElement.tabIndex = 0;
      const refreshTheme = () => cy.style(stylesheet()).update();
      themeSelect?.addEventListener("change", refreshTheme);
      say(`${nodes.length} genres loaded. ${["Umbrella genres", "Genres", "Subgenres", "Detailed genres"][currentLod]}.`);
    })
    .catch(() => say("Interactive map unavailable. The accessible map links remain available."));

  query?.addEventListener("htmx:afterRequest", () => {
    // Search updates its own results panel and intentionally does not recreate the map.
  });
})();
