(() => {
  "use strict";

  const mapElement = document.querySelector("#semantic-map");
  if (!mapElement || !window.cytoscape) return;

  const status = document.querySelector("#map-status");
  const root = document.documentElement;
  const themeSelect = document.querySelector("#theme-select");
  const themeToggle = document.querySelector("#theme-toggle");
  const query = document.querySelector("#query");
  const graphUrl = mapElement.dataset.graphUrl;
  const preferredDark = window.matchMedia("(prefers-color-scheme: dark)");
  let currentLod = -1;
  let selectedNode = null;

  const say = (message) => {
    if (status) status.textContent = message;
  };

  const setTheme = (value) => {
    const mode = value === "system" ? (preferredDark.matches ? "dark" : "light") : value;
    root.dataset.theme = mode;
    if (themeSelect) themeSelect.value = value;
    if (themeToggle) themeToggle.textContent = mode === "dark" ? "Light" : "Dark";
    window.localStorage.setItem("musix-theme", value);
  };

  let keyboardNavigation = false;
  document.addEventListener("keydown", (event) => {
    if (event.key === "Tab") keyboardNavigation = true;
  }, true);
  mapElement.addEventListener("focus", () => {
    if (keyboardNavigation) mapElement.classList.add("keyboard-focus-visible");
  });
  mapElement.addEventListener("blur", () => mapElement.classList.remove("keyboard-focus-visible"));

  const requestedTheme = new URLSearchParams(window.location.search).get("theme");
  const storedTheme = ["light", "dark", "system"].includes(requestedTheme)
    ? requestedTheme
    : window.localStorage.getItem("musix-theme") || "light";
  setTheme(storedTheme);
  themeSelect?.addEventListener("change", () => setTheme(themeSelect.value));
  themeToggle?.addEventListener("click", () => setTheme(root.dataset.theme === "dark" ? "light" : "dark"));
  preferredDark.addEventListener("change", () => {
    if ((window.localStorage.getItem("musix-theme") || "system") === "system") setTheme("system");
  });

  const nodeId = (raw) => `genre-${raw.genre_id ?? raw.id}`;
  const getNodes = (payload) => payload.nodes ?? payload.graph?.nodes ?? payload.points ?? [];
  const getEdges = (payload) => payload.edges ?? payload.graph?.edges ?? [];
  const getLods = (payload) => payload.lods ?? payload.graph?.lods ?? [];
  const getOverviewCommunities = (payload) => payload.overview_communities ?? [];

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
    const communities = getOverviewCommunities(payload);
    const positions = normalisedPositions(nodes);
    const nodesById = new Map(nodes.map((node) => [node.genre_id ?? node.id, node]));
    const overviewLabel = (community) => {
      const lead = community.member_entity_ids.map((id) => nodesById.get(id)).filter(Boolean).sort(
        (left, right) => Number(right.direct_artist_count ?? 0) - Number(left.direct_artist_count ?? 0)
          || Number(right.subtree_size ?? 0) - Number(left.subtree_size ?? 0)
          || String(left.name).localeCompare(String(right.name)),
      )[0];
      return lead ? lead.name : `${community.member_entity_ids.length} genres`;
    };
    const elements = communities.map((community) => ({
      data: {
        id: community.community_id,
        itemId: community.community_id,
        genreId: community.community_id,
        label: overviewLabel(community),
        detailHref: null,
        depth: 0,
        lodMin: 0,
        weight: community.member_entity_ids.length,
        displayLabel: "",
        labelSize: 13,
        overview: true,
      },
      position: { x: 180 + Number(community.x) * 2200, y: 160 + Number(community.y) * 1500 },
      classes: "overview",
    }));
    elements.push(...nodes.map((node) => {
      const id = nodeId(node);
      return {
        data: {
          id,
          itemId: node.genre_id ?? node.id,
          genreId: node.genre_id ?? node.id,
          label: node.name,
          detailHref: node.detail_href ?? payload.detail_hrefs?.[node.genre_id ?? node.id] ?? null,
          depth: node.depth ?? 1,
          // Legacy point responses have no semantic tiers; keep them usable while
          // production-map-v1 supplies its explicit `lod_min` contract.
          lodMin: node.lod_min ?? 0,
          weight: node.display_weight ?? node.weight ?? 0,
          displayLabel: "",
          labelSize: 13,
          overview: false,
          subtreeSize: node.subtree_size ?? 0,
          communityId: node.community_id ?? "",
        },
        position: positions.get(id),
        classes: node.display_parent_id === null || node.display_parent_id === undefined ? "umbrella" : "genre",
      };
    }));
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
    { selector: "node", style: { "background-color": cssValue("--node"), label: "data(displayLabel)", color: cssValue("--ink"), "font-size": "data(labelSize)", "text-outline-color": cssValue("--canvas"), "text-outline-width": 3, "text-valign": "bottom", "text-margin-y": 7, width: 13, height: 13, "overlay-opacity": 0 } },
    { selector: "node.umbrella", style: { "background-color": cssValue("--parent"), width: 25, height: 25, "font-size": "data(labelSize)", "font-weight": 700, "border-width": 2, "border-color": cssValue("--node") } },
    { selector: "node.overview", style: { "background-color": cssValue("--parent"), width: 28, height: 28, "font-size": "data(labelSize)", "font-weight": 700, "border-width": 2, "border-color": cssValue("--node") } },
    { selector: "node:selected", style: { "border-width": 4, "border-color": cssValue("--focus"), "background-color": cssValue("--focus") } },
    { selector: "edge", style: { width: 1.5, "line-color": cssValue("--edge"), opacity: 0.68, "curve-style": "straight" } },
    { selector: "edge.similarity", style: { "line-style": "dashed", "line-color": cssValue("--similarity"), opacity: 0.65 } },
    { selector: ".lod-hidden", style: { display: "none" } },
    { selector: ".edge-hidden", style: { display: "none" } },
  ];

  const lodForZoom = (zoom) => zoom < 0.58 ? 0 : zoom < 0.95 ? 1 : zoom < 1.55 ? 2 : 3;
  const labelBudget = (lod) => (mapElement.clientWidth <= 600
    ? [24, 32, 48, 64][lod]
    : [24, 60, 96, 140][lod]);

  const intersects = (first, second) => first.x1 < second.x2 && first.x2 > second.x1
    && first.y1 < second.y2 && first.y2 > second.y1;

  const renderedLabelBounds = (cy, node) => {
    // Cytoscape exposes the renderer's calculated text bounds on the live node.
    // renderedBoundingBox({includeLabels:true}) unions that with the circle,
    // which is not a text-label measurement.
    node.boundingBox({ includeLabels: true });
    const bounds = node[0]._private.labelBounds.main;
    const pan = cy.pan();
    const zoom = cy.zoom();
    return {
      x1: bounds.x1 * zoom + pan.x,
      y1: bounds.y1 * zoom + pan.y,
      x2: bounds.x2 * zoom + pan.x,
      y2: bounds.y2 * zoom + pan.y,
    };
  };

  const labelCandidates = (cy, overview, lod) => cy.nodes().filter((node) => overview
    ? Boolean(node.data("overview"))
    : !node.data("overview") && Number(node.data("lodMin")) <= lod).sort((left, right) => (
    Number(right === selectedNode) - Number(left === selectedNode)
    || Number(right.data("weight")) - Number(left.data("weight"))
    || String(left.data("label")).localeCompare(String(right.data("label")))
  ));

  const setVisibleEdges = (cy) => {
    cy.edges().forEach((edge) => {
      const selected = selectedNode && (edge.source() === selectedNode || edge.target() === selectedNode);
      const visible = selected && !edge.source().hasClass("lod-hidden") && !edge.target().hasClass("lod-hidden");
      edge.toggleClass("edge-hidden", !visible);
    });
  };

  const statusMessage = (payload, lod) => lod === 0
    ? `${getOverviewCommunities(payload).length} overview communities; ${getNodes(payload).length} genres available. Overview level.`
    : `${getNodes(payload).length} genres available. ${["", "Genre", "Subgenre", "Detailed genre"][lod]} level.`;

  const setCollisionFreeLabels = (cy, lod, overview) => {
    const acceptedBoxes = [];
    const viewport = mapElement.getBoundingClientRect();
    let accepted = 0;
    const candidates = labelCandidates(cy, overview, lod);
    cy.nodes().forEach((node) => node.data("displayLabel", ""));
    for (const node of candidates) {
      if (accepted === labelBudget(lod)) break;
      node.data("displayLabel", node.data("label"));
      // This is the same live renderer geometry collected by browser QA. It keeps
      // the UI from rendering a label the map cannot actually show clearly.
      const bounds = renderedLabelBounds(cy, node);
      const inViewport = bounds.x1 >= viewport.left + 4 && bounds.y1 >= viewport.top + 4
        && bounds.x2 <= viewport.right - 4 && bounds.y2 <= viewport.bottom - 4;
      if (!inViewport || acceptedBoxes.some((other) => intersects(bounds, other))) {
        node.data("displayLabel", "");
        continue;
      }
      acceptedBoxes.push(bounds);
      accepted += 1;
    }
  };

  const updateLod = (cy, payload) => {
    const lod = lodForZoom(cy.zoom());
    if (lod === currentLod) {
      const showingOverview = lod === 0 && getOverviewCommunities(payload).length > 0;
      setCollisionFreeLabels(cy, lod, showingOverview);
      setVisibleEdges(cy);
      return;
    }
    currentLod = lod;
    const communities = getOverviewCommunities(payload);
    const showingOverview = lod === 0 && communities.length > 0;
    const descriptor = getLods(payload).find((item) => Number(item.level) === lod);
    const visibleIds = new Set(showingOverview
      ? communities.map((item) => item.community_id)
      : descriptor?.visible_node_ids ?? cy.nodes().filter(
      (node) => Number(node.data("lodMin")) <= lod,
    ).map((node) => node.data("itemId")));
    const labelSize = [12, 14, 13, 12][lod];
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const visible = visibleIds.has(node.data("itemId"));
        node.toggleClass("lod-hidden", !visible);
        node.data("labelSize", labelSize);
      });
      cy.edges().forEach((edge) => edge.toggleClass("lod-hidden", edge.source().hasClass("lod-hidden") || edge.target().hasClass("lod-hidden")));
    });
    setCollisionFreeLabels(cy, lod, showingOverview);
    setVisibleEdges(cy);
    say(statusMessage(payload, lod));
  };

  const selectGenre = (cy, node, payload) => {
    cy.$(":selected").unselect();
    node.select();
    selectedNode = node;
    setVisibleEdges(cy);
    setCollisionFreeLabels(
      cy,
      currentLod,
      currentLod === 0 && getOverviewCommunities(payload).length > 0,
    );
    const detailHref = node.data("detailHref");
    if (detailHref && window.htmx) {
      // The graph owns its persistent canvas. Keep HTMX history from restoring
      // a stale DOM snapshot that has no live renderer after browser Back.
      window.htmx.ajax("GET", detailHref, { target: "#genre-detail-slot", swap: "innerHTML" });
      window.history.pushState({ musixGenreDetail: detailHref }, "", detailHref);
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
      window.__musixMap = cy;
      root.classList.add("js-map-ready");
      cy.resize();
      // Start at the actual overview level. A later fit-to-overview jump used to
      // skip semantic level zero and make the first view look tiny and sparse.
      cy.zoom(0.42);
      updateLod(cy, payload);
      cy.center(cy.elements(":visible"));
      updateLod(cy, payload);
      cy.on("zoom", () => updateLod(cy, payload));
      cy.on("pan", () => updateLod(cy, payload));
      cy.on("tap", "node", (event) => selectGenre(cy, event.target, payload));
      cy.on("tap", (event) => {
        if (event.target === cy) {
          cy.$(":selected").unselect();
          selectedNode = null;
          setVisibleEdges(cy);
        }
      });

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
      window.addEventListener("popstate", (event) => {
        // HTMX's body-snapshot restoration disconnects a canvas renderer while
        // leaving its old object in window. This map owns history selection, so
        // handle its entries during capture before HTMX can restore a stale body.
        event.stopImmediatePropagation();
        const detail = window.location.pathname.startsWith("/genres/key/") ? window.location.pathname : null;
        if (detail && window.htmx) {
          window.htmx.ajax("GET", detail, { target: "#genre-detail-slot", swap: "innerHTML" });
        } else {
          const slot = document.querySelector("#genre-detail-slot");
          if (slot) slot.innerHTML = "";
          cy.$(":selected").unselect();
          selectedNode = null;
          setVisibleEdges(cy);
          say(statusMessage(payload, currentLod));
        }
      }, { capture: true });
    })
    .catch(() => say("Interactive map unavailable. The accessible map links remain available."));

  query?.addEventListener("htmx:afterRequest", () => {
    // Search updates its own results panel and intentionally does not recreate the map.
  });
})();
