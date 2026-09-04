(() => {
  "use strict";

  let mapElement = document.querySelector("#semantic-map");
  if (!mapElement || !window.cytoscape) return;

  const root = document.documentElement;
  // Genre details use an explicit browser history entry. HTMX snapshot history
  // can replace the renderer DOM with an inert cached canvas on Back, so leave
  // this persistent map outside that secondary history mechanism.
  if (window.htmx) window.htmx.config.history = false;
  const themeSelect = document.querySelector("#theme-select");
  const themeToggle = document.querySelector("#theme-toggle");
  const query = document.querySelector("#query");
  const graphUrl = mapElement.dataset.graphUrl;
  const preferredDark = window.matchMedia("(prefers-color-scheme: dark)");
  let currentLod = -1;
  let selectedNode = null;
  let activeCommunity = null;
  let cameraTransition = false;
  let lodFrame = null;
  let overviewZoom = 1;

  const say = (message) => {
    const liveStatus = document.querySelector("#map-status");
    if (liveStatus) liveStatus.textContent = message;
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
  const nodePositionCache = new WeakMap();
  const edgeIndexCache = new WeakMap();
  let nodePositionBuilds = 0;
  const overviewProminence = (members) => Math.min(1, Math.log2(Math.max(1, members) + 1) / 6);
  const overviewFontSize = (members) => {
    const mobile = mapElement.clientWidth <= 600;
    const minimum = mobile ? 14 : 16;
    const maximum = mobile ? 20 : 24;
    return Math.round(minimum + (maximum - minimum) * overviewProminence(members));
  };
  const overviewFitPadding = () => mapElement.clientWidth <= 600 ? 28 : 72;
  const overviewDimensions = () => ({
    width: Math.max(1, mapElement.clientWidth || window.innerWidth),
    height: Math.max(1, mapElement.clientHeight || window.innerHeight),
  });
  const mapDimensions = () => {
    const padding = overviewFitPadding();
    const usableWidth = Math.max(1, mapElement.clientWidth - 2 * padding);
    const usableHeight = Math.max(1, mapElement.clientHeight - 2 * padding);
    // A generous preset space leaves room for collision-free labels before
    // Cytoscape fits the actual viewport.
    return { width: 2000 * usableWidth / usableHeight, height: 2000 };
  };

  const quantile = (values, fraction) => values[Math.min(values.length - 1, Math.max(0, Math.round((values.length - 1) * fraction)))];
  const mapPositions = (items, id, dimensions = mapDimensions()) => {
    const axis = (key) => items.map((item) => Number(item[key])).filter(Number.isFinite).sort((a, b) => a - b);
    const xs = axis("x"); const ys = axis("y");
    const lowX = quantile(xs, 0.05); const highX = quantile(xs, 0.95);
    const lowY = quantile(ys, 0.05); const highY = quantile(ys, 0.95);
    const tailRanks = (values, low, high) => {
      const ranks = (tail) => new Map(tail.map((value, index) => [value, index]));
      const lower = values.filter((value) => value < low);
      const upper = values.filter((value) => value > high);
      return { lower, upper, lowerRanks: ranks(lower), upperRanks: ranks(upper) };
    };
    const xTails = tailRanks(xs, lowX, highX); const yTails = tailRanks(ys, lowY, highY);
    const scale = (raw, low, high, tails) => {
      const value = Number(raw);
      const tailPosition = (rank, count, start, end) => count <= 1
        ? (start + end) / 2
        : start + (end - start) * rank / (count - 1);
      if (value < low) return tailPosition(tails.lowerRanks.get(value) ?? 0, tails.lower.length, 0.02, 0.06);
      if (value > high) return tailPosition(tails.upperRanks.get(value) ?? 0, tails.upper.length, 0.94, 0.98);
      return 0.06 + 0.88 * (value - low) / Math.max(high - low, 0.0001);
    };
    return new Map(items.map((item) => [id(item), {
      x: scale(item.x, lowX, highX, xTails) * dimensions.width,
      y: scale(item.y, lowY, highY, yTails) * dimensions.height,
    }]));
  };
  const spreadOverviewPositions = (communities) => {
    const dimensions = overviewDimensions();
    const positions = mapPositions(communities, (community) => community.community_id, dimensions);
    const points = communities.map((community) => ({
      id: community.community_id,
      ...positions.get(community.community_id),
    }));
    const mobile = mapElement.clientWidth <= 600;
    const horizontalInset = mobile ? 36 : 110;
    const verticalInset = mobile ? 126 : 100;
    const minimumDistance = mobile ? 64 : 96;
    // This deterministic display adjustment retains the relative input map as
    // its starting point while separating dense overview anchors for readable labels.
    for (let iteration = 0; iteration < 90; iteration += 1) {
      for (let leftIndex = 0; leftIndex < points.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < points.length; rightIndex += 1) {
          const left = points[leftIndex]; const right = points[rightIndex];
          let dx = left.x - right.x; let dy = left.y - right.y;
          let distance = Math.hypot(dx, dy);
          if (distance >= minimumDistance) continue;
          if (distance < 0.001) {
            dx = left.id < right.id ? -1 : 1;
            dy = left.id < right.id ? -0.5 : 0.5;
            distance = Math.hypot(dx, dy);
          }
          const movement = (minimumDistance - distance) * 0.08 / distance;
          left.x += dx * movement; left.y += dy * movement;
          right.x -= dx * movement; right.y -= dy * movement;
        }
      }
      for (const point of points) {
        point.x = Math.max(horizontalInset, Math.min(dimensions.width - horizontalInset, point.x));
        point.y = Math.max(verticalInset, Math.min(dimensions.height - verticalInset, point.y));
      }
    }
    if (mapElement.clientWidth > 600) {
      // Preserve ordinal source placement while spreading the dense left-side
      // cluster across a usable landscape overview.
      [...points].sort((left, right) => left.x - right.x || left.id.localeCompare(right.id)).forEach((point, index) => {
        const target = horizontalInset + (dimensions.width - 2 * horizontalInset) * index / Math.max(1, points.length - 1);
        point.x = point.x * 0.1 + target * 0.9;
      });
    }
    return new Map(points.map((point) => [point.id, { x: point.x, y: point.y }]));
  };
  const nodePositions = (payload) => {
    const cached = nodePositionCache.get(payload);
    if (cached) return cached;
    const positions = mapPositions(getNodes(payload), nodeId);
    nodePositionCache.set(payload, positions);
    nodePositionBuilds += 1;
    return positions;
  };
  const edgesByEndpoint = (payload) => {
    const cached = edgeIndexCache.get(payload);
    if (cached) return cached;
    const index = new Map();
    for (const edge of getEdges(payload)) {
      for (const endpoint of [edge.source_genre_id ?? edge.source, edge.target_genre_id ?? edge.target]) {
        const entries = index.get(endpoint) ?? [];
        entries.push(edge);
        index.set(endpoint, entries);
      }
    }
    edgeIndexCache.set(payload, index);
    return index;
  };

  const elementsFor = (payload) => {
    const nodes = getNodes(payload);
    const communities = getOverviewCommunities(payload);
    const overviewPositions = spreadOverviewPositions(communities);
    const nodesById = new Map(nodes.map((node) => [node.genre_id ?? node.id, node]));
    const overviewLabel = (community) => {
      const lead = community.member_entity_ids.map((id) => nodesById.get(id)).filter(Boolean).sort(
        (left, right) => Number(right.direct_artist_count ?? 0) - Number(left.direct_artist_count ?? 0)
          || Number(right.subtree_size ?? 0) - Number(left.subtree_size ?? 0)
          || String(left.name).localeCompare(String(right.name)),
      )[0];
      return lead ? lead.name : `${community.member_entity_ids.length} genres`;
    };
    const elements = communities.map((community) => {
      const memberCount = community.member_entity_ids.length;
      return {
      data: {
        id: community.community_id,
        itemId: community.community_id,
        genreId: community.community_id,
        label: community.name ?? overviewLabel(community),
        detailHref: null,
        depth: 0,
        lodMin: 0,
        weight: memberCount,
        displayLabel: "",
        labelSize: overviewFontSize(memberCount),
        overviewNodeSize: Math.round(42 + 34 * overviewProminence(memberCount)),
        memberEntityIds: community.member_entity_ids,
        overview: true,
      },
      position: overviewPositions.get(community.community_id),
      classes: "overview",
      };
    });
    return elements;
  };

  const nodeElement = (node, payload) => {
      const positions = nodePositions(payload);
      const id = nodeId(node);
      return {
        data: {
          id,
          itemId: node.genre_id ?? node.id,
          genreId: node.genre_id ?? node.id,
          label: node.name,
          detailHref: node.detail_href ?? payload.detail_hrefs?.[node.genre_id ?? node.id] ?? null,
          depth: node.depth ?? 1,
          lodMin: node.lod_min ?? 3,
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
  };

  const materializeLod = (cy, payload, lod, memberIds = null) => {
    if (lod === 0) return;
    const descriptor = getLods(payload).find((item) => Number(item.level) === lod);
    const allowed = new Set(descriptor?.visible_node_ids ?? []);
    const communityMembers = memberIds ? new Set(memberIds) : null;
    // A focused community is a bounded, intentional cohort. Do not mix it
    // with the global LOD list then slice it away by popularity.
    const allowedIds = communityMembers ?? allowed;
    const cap = communityMembers ? communityMembers.size : [0, 96, 280, 720][lod];
    const candidates = getNodes(payload).filter((node) => allowedIds.has(node.genre_id ?? node.id)).sort(
      (left, right) => Number(right.direct_artist_count ?? 0) - Number(left.direct_artist_count ?? 0)
        || String(left.name).localeCompare(String(right.name)),
    ).slice(0, cap);
    const additions = candidates.filter((node) => cy.$id(nodeId(node)).empty()).map((node) => nodeElement(node, payload));
    if (additions.length) cy.batch(() => cy.add(additions));
  };

  const materializeSelectedEdges = (cy, payload, node) => {
    const id = node.data("itemId");
    const additions = (edgesByEndpoint(payload).get(id) ?? []).slice(0, 12).flatMap((edge) => {
      const source = `genre-${edge.source_genre_id ?? edge.source}`;
      const target = `genre-${edge.target_genre_id ?? edge.target}`;
      const edgeId = `${edge.kind ?? "similarity"}-${source}-${target}`;
      if (cy.$id(source).empty() || cy.$id(target).empty() || !cy.$id(edgeId).empty()) return [];
      return [{ data: { id: edgeId, source, target, kind: edge.kind ?? "similarity", weight: edge.weight ?? 0 }, classes: edge.kind ?? "similarity" }];
    });
    if (additions.length) cy.batch(() => cy.add(additions));
  };

  const cssValue = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  const stylesheet = () => [
    { selector: "node", style: { "background-color": cssValue("--node"), label: "data(displayLabel)", color: cssValue("--ink"), "font-size": "data(labelSize)", "text-outline-color": cssValue("--canvas"), "text-outline-width": 3, "text-valign": "bottom", "text-margin-y": 7, width: 13, height: 13, "overlay-opacity": 0 } },
    { selector: "node.umbrella", style: { "background-color": cssValue("--parent"), width: 25, height: 25, "font-size": "data(labelSize)", "font-weight": 700, "border-width": 2, "border-color": cssValue("--node") } },
    { selector: "node.overview", style: { "background-color": cssValue("--parent"), "background-opacity": 0.9, width: "data(overviewNodeSize)", height: "data(overviewNodeSize)", "font-size": "data(labelSize)", "font-weight": 700, "border-width": 2, "border-color": cssValue("--node") } },
    { selector: "node:selected", style: { "border-width": 4, "border-color": cssValue("--focus"), "background-color": cssValue("--focus") } },
    { selector: "edge", style: { width: 1.5, "line-color": cssValue("--edge"), opacity: 0.68, "curve-style": "straight" } },
    { selector: "edge.similarity", style: { "line-style": "dashed", "line-color": cssValue("--similarity"), opacity: 0.65 } },
    { selector: ".lod-hidden", style: { display: "none" } },
    { selector: ".edge-hidden", style: { display: "none" } },
  ];

  const lodForZoom = (zoom) => {
    const relative = zoom / Math.max(overviewZoom, 0.0001);
    return relative < 1.25 ? 0 : relative < 2 ? 1 : relative < 3 ? 2 : 3;
  };
  const fitOverview = (cy) => {
    cy.zoom(1);
    cy.pan({ x: 0, y: 0 });
    overviewZoom = 1;
  };
  const labelBudget = (lod) => (mapElement.clientWidth <= 600
    ? [8, 32, 48, 64][lod]
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

  const labelCandidates = (cy, overview, lod) => {
    const focusedMembers = new Set(activeCommunity?.data("memberEntityIds") ?? []);
    return cy.nodes().filter((node) => (
      overview
        ? Boolean(node.data("overview"))
        : (!node.data("overview") && (
          Number(node.data("lodMin")) <= lod || focusedMembers.has(node.data("itemId"))
        ))
    )).sort((left, right) => (
      Number(focusedMembers.has(right.data("itemId"))) - Number(focusedMembers.has(left.data("itemId")))
      || Number(right.data("weight")) - Number(left.data("weight"))
      || String(left.data("label")).localeCompare(String(right.data("label")))
    ));
  };

  const setVisibleEdges = (cy) => {
    if (activeCommunity) {
      cy.edges().addClass("edge-hidden");
      return;
    }
    cy.edges().forEach((edge) => {
      const selected = selectedNode && (edge.source() === selectedNode || edge.target() === selectedNode);
      const visible = selected && !edge.source().hasClass("lod-hidden") && !edge.target().hasClass("lod-hidden");
      edge.toggleClass("edge-hidden", !visible);
    });
  };

  const rendererIsLive = (cy, container) => {
    if (!container) return false;
    const canvases = [...container.querySelectorAll("canvas")];
    return Boolean(
      cy && container.isConnected && cy.container() === container
      && canvases.some((canvas) => canvas.isConnected && canvas.width > 0
        && canvas.height > 0 && canvas.getBoundingClientRect().width > 0),
    );
  };

  const statusMessage = (payload, lod) => lod === 0
    ? `${getOverviewCommunities(payload).length} overview communities; ${getNodes(payload).length} genres available. Overview level.`
    : `${getNodes(payload).length} genres available. ${["", "Genre", "Subgenre", "Detailed genre"][lod]} level.`;

  const setCollisionFreeLabels = (cy, lod, overview) => {
    const acceptedBoxes = [];
    const viewport = mapElement.getBoundingClientRect();
    let accepted = 0;
    const focusedMemberCount = activeCommunity?.data("memberEntityIds")?.length ?? 0;
    const focusedSmallCommunity = !overview && focusedMemberCount > 0 && focusedMemberCount <= 12;
    const candidates = labelCandidates(cy, overview, lod);
    const placements = overview || focusedSmallCommunity
      ? [
        { "text-halign": "center", "text-valign": "bottom", "text-margin-x": 0, "text-margin-y": 7 },
        { "text-halign": "center", "text-valign": "top", "text-margin-x": 0, "text-margin-y": -7 },
        { "text-halign": "left", "text-valign": "center", "text-margin-x": 7, "text-margin-y": 0 },
        { "text-halign": "right", "text-valign": "center", "text-margin-x": -7, "text-margin-y": 0 },
        { "text-halign": "center", "text-valign": "bottom", "text-margin-x": 0, "text-margin-y": 28 },
        { "text-halign": "left", "text-valign": "center", "text-margin-x": 28, "text-margin-y": 0 },
        { "text-halign": "right", "text-valign": "center", "text-margin-x": -28, "text-margin-y": 0 },
        { "text-halign": "center", "text-valign": "bottom", "text-margin-x": 0, "text-margin-y": 52 },
        { "text-halign": "center", "text-valign": "top", "text-margin-x": 0, "text-margin-y": -52 },
        { "text-halign": "left", "text-valign": "center", "text-margin-x": 52, "text-margin-y": 0 },
        { "text-halign": "right", "text-valign": "center", "text-margin-x": -52, "text-margin-y": 0 },
      ]
      : [{ "text-halign": "center", "text-valign": "bottom", "text-margin-x": 0, "text-margin-y": 7 }];
    cy.nodes().forEach((node) => {
      node.data("displayLabel", "");
      node.removeStyle("text-halign");
      node.removeStyle("text-valign");
      node.removeStyle("text-margin-x");
      node.removeStyle("text-margin-y");
    });
    for (const node of candidates) {
      if (accepted === (focusedSmallCommunity ? focusedMemberCount : labelBudget(lod))) break;
      node.data("displayLabel", node.data("label"));
      let chosen = false;
      for (const placement of placements) {
        node.style(placement);
        // This is the same live renderer geometry collected by browser QA. It
        // keeps the UI from rendering a label the map cannot actually show.
        const bounds = renderedLabelBounds(cy, node);
        const textInset = mapElement.clientWidth <= 600 ? 18 : 8;
        const inViewport = bounds.x1 >= viewport.left + textInset && bounds.y1 >= viewport.top + textInset
          && bounds.x2 <= viewport.right - textInset && bounds.y2 <= viewport.bottom - textInset;
        if (!inViewport || acceptedBoxes.some((other) => intersects(bounds, other))) continue;
        acceptedBoxes.push(bounds);
        accepted += 1;
        chosen = true;
        break;
      }
      if (!chosen) {
        node.data("displayLabel", "");
        continue;
      }
    }
  };

  const updateLod = (cy, payload) => {
    // A wide community may need a low physical zoom to keep every member in
    // frame. It is still semantically the genre drill level, never overview.
    const lod = activeCommunity ? Math.max(1, lodForZoom(cy.zoom())) : lodForZoom(cy.zoom());
    // `fit()` briefly crosses the overview threshold while it calculates a
    // community camera. That must not cancel the drill state mid-transition.
    if (activeCommunity && lod === 0 && !cameraTransition) {
      const url = new URL(window.location.href);
      url.searchParams.delete("overview");
      window.history.replaceState({}, "", url);
      resetCommunity(cy, payload);
      return;
    }
    if (lod === currentLod) {
      const showingOverview = lod === 0 && getOverviewCommunities(payload).length > 0;
      setCollisionFreeLabels(cy, lod, showingOverview);
      setVisibleEdges(cy);
      return;
    }
    currentLod = lod;
    const communities = getOverviewCommunities(payload);
    const showingOverview = lod === 0 && communities.length > 0;
    const focusedMembers = activeCommunity?.data("memberEntityIds") ?? null;
    materializeLod(cy, payload, lod, focusedMembers);
    const descriptor = getLods(payload).find((item) => Number(item.level) === lod);
    const visibleIds = new Set(showingOverview
      ? communities.map((item) => item.community_id)
      : descriptor?.visible_node_ids ?? cy.nodes().filter(
      (node) => Number(node.data("lodMin")) <= lod,
    ).map((node) => node.data("itemId")));
    if (activeCommunity && !showingOverview) {
      visibleIds.clear();
      for (const memberId of focusedMembers) visibleIds.add(memberId);
      visibleIds.add(activeCommunity.data("itemId"));
    }
    const labelSize = [12, mapElement.clientWidth <= 600 ? 24 : 14, 13, 12][lod];
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const visible = visibleIds.has(node.data("itemId"));
        node.toggleClass("lod-hidden", !visible);
        node.data(
          "labelSize",
          Boolean(node.data("overview"))
            ? overviewFontSize(Number(node.data("weight")))
            : labelSize,
        );
      });
      cy.edges().forEach((edge) => edge.toggleClass("lod-hidden", edge.source().hasClass("lod-hidden") || edge.target().hasClass("lod-hidden")));
    });
    setCollisionFreeLabels(cy, lod, showingOverview);
    setVisibleEdges(cy);
    if (activeCommunity && !showingOverview) {
      const shownMembers = [...visibleIds].filter((id) => id !== activeCommunity.data("itemId")).length;
      say(`${activeCommunity.data("label")}; ${shownMembers} member genres. Genre level.`);
    } else say(statusMessage(payload, lod));
  };

  const focusCommunity = (cy, node, payload) => {
    if (activeCommunity?.id() === node.id()) return;
    cameraTransition = true;
    // A pointer drill owns the keyboard continuation too: Escape is the
    // explicit, accessible way back to the overview.
    mapElement.focus({ preventScroll: true });
    selectedNode = node;
    activeCommunity = node;
    cy.$(":selected").unselect();
    node.select();
    const memberIds = node.data("memberEntityIds") ?? [];
    materializeLod(cy, payload, 1, memberIds);
    const members = memberIds.reduce(
      (collection, id) => collection.union(cy.$id(`genre-${id}`)),
      cy.collection(),
    );
    const visible = members.union(node);
    // Keep room for the focused cohort's readable alternate label placements,
    // rather than fitting circles flush to the viewport edge.
    if (visible.nonempty()) {
      const focusPadding = memberIds.length <= 12
        ? mapElement.clientWidth <= 600 ? 40 : 144
        : 96;
      cy.fit(visible, focusPadding);
    }
    currentLod = -1;
    cameraTransition = false;
    updateLod(cy, payload);
    window.__musixMapMetrics.activeCommunityId = node.data("itemId");
    say(`${node.data("label")}; ${memberIds.length} member genres revealed. Genre level.`);
  };

  const resetCommunity = (cy, payload) => {
    cameraTransition = true;
    activeCommunity = null;
    selectedNode = null;
    cy.$(":selected").unselect();
    fitOverview(cy);
    currentLod = -1;
    cameraTransition = false;
    updateLod(cy, payload);
    window.__musixMapMetrics.activeCommunityId = null;
    say(statusMessage(payload, 0));
  };

  const returnToOverview = (cy, payload) => {
    // Community drill is transient local camera state. It intentionally does
    // not create HTMX/browser history entries that can detach this canvas.
    resetCommunity(cy, payload);
  };

  const selectGenre = (cy, node, payload) => {
    if (node.data("overview")) {
      focusCommunity(cy, node, payload);
      return;
    }
    cy.$(":selected").unselect();
    node.select();
    selectedNode = node;
    materializeSelectedEdges(cy, payload, node);
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
    const fallbackLink = document.querySelector(`#map-point-${CSS.escape(String(node.data("genreId")))}`);
    if (fallbackLink) fallbackLink.click();
  };

  const bindMapInteractions = (cy, payload) => {
    const scheduleLodUpdate = () => {
      if (lodFrame !== null) return;
      lodFrame = window.requestAnimationFrame(() => {
        lodFrame = null;
        updateLod(cy, payload);
      });
    };
    cy.on("zoom", scheduleLodUpdate);
    cy.on("pan", scheduleLodUpdate);
    cy.on("tap", "node", (event) => selectGenre(cy, event.target, payload));
    cy.on("tap", (event) => {
      if (event.target !== cy) return;
      if (activeCommunity) {
        returnToOverview(cy, payload);
        return;
      }
      cy.$(":selected").unselect();
      selectedNode = null;
      setVisibleEdges(cy);
    });
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
      window.__musixMapMetrics = {
        initialElementCount: cy.elements().length,
        nodePositionBuilds,
        activeCommunityId: null,
      };
      root.classList.add("js-map-ready");
      cy.resize();
      // Fit establishes the semantic overview baseline. LOD thresholds are
      // relative to this fitted zoom, so every viewport starts at overview.
      fitOverview(cy);
      updateLod(cy, payload);
      bindMapInteractions(cy, payload);

      const selected = mapElement.dataset.selectedGenre;
      if (selected) cy.$(`#genre-${selected}`).select();
      // Capture-phase delegation keeps controls reliable above Cytoscape's
      // canvas, including on a remounted map after browser history restores.
      document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-map-action]");
        if (!button) return;
        const action = button.dataset.mapAction;
        event.preventDefault();
        if (action === "zoom-in") cy.zoom({ level: Math.min(cy.maxZoom(), cy.zoom() * 1.25), renderedPosition: { x: innerWidth / 2, y: innerHeight / 2 } });
        if (action === "zoom-out") cy.zoom({ level: Math.max(cy.minZoom(), cy.zoom() / 1.25), renderedPosition: { x: innerWidth / 2, y: innerHeight / 2 } });
        if (action === "fit") {
          if (activeCommunity) returnToOverview(cy, payload);
          else cy.fit(cy.elements(":visible"), overviewFitPadding());
        }
      }, true);
      mapElement.addEventListener("keydown", (event) => {
        const key = event.key;
        if (["+", "=", "-", "_", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Escape"].includes(key)) event.preventDefault();
        if (key === "+" || key === "=") cy.zoom(cy.zoom() * 1.2);
        if (key === "-" || key === "_") cy.zoom(cy.zoom() / 1.2);
        if (key === "ArrowUp") cy.panBy({ x: 0, y: 60 });
        if (key === "ArrowDown") cy.panBy({ x: 0, y: -60 });
        if (key === "ArrowLeft") cy.panBy({ x: 60, y: 0 });
        if (key === "ArrowRight") cy.panBy({ x: -60, y: 0 });
        if (key === "Escape") {
          if (activeCommunity) returnToOverview(cy, payload);
          else cy.$(":selected").unselect();
        }
      });
      mapElement.tabIndex = 0;
      const refreshTheme = () => cy.style(stylesheet()).update();
      themeSelect?.addEventListener("change", refreshTheme);
      const remountAfterHistoryRestore = (snapshot) => {
        const liveMap = document.querySelector("#semantic-map");
        if (!liveMap || rendererIsLive(window.__musixMap, liveMap)) return;
        window.__musixMap?.destroy();
        mapElement = liveMap;
        currentLod = -1;
        selectedNode = null;
        activeCommunity = null;
        cameraTransition = false;
        const replacement = window.cytoscape({
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
        window.__musixMap = replacement;
        mapElement.tabIndex = 0;
        replacement.resize();
        replacement.zoom(snapshot.zoom);
        replacement.pan(snapshot.pan);
        updateLod(replacement, payload);
        bindMapInteractions(replacement, payload);
        window.requestAnimationFrame(() => {
          replacement.resize();
          replacement.pan(snapshot.pan);
          replacement.zoom(snapshot.zoom);
          updateLod(replacement, payload);
        });
      };
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
          if (activeCommunity) resetCommunity(cy, payload);
          else {
            cy.$(":selected").unselect();
            selectedNode = null;
            setVisibleEdges(cy);
          }
          // Capture after an overview reset. Restoring the pre-Back focus
          // camera would turn a correct overview Back into an empty LOD state.
          const liveCy = window.__musixMap ?? cy;
          const snapshot = { pan: liveCy.pan(), zoom: liveCy.zoom() };
          const restoreStatus = () => say(statusMessage(payload, currentLod));
          restoreStatus();
          // A browser Back can finish an HTMX cache restore after popstate. Write
          // into the currently connected live region after those microtasks too.
          window.setTimeout(restoreStatus, 0);
          window.setTimeout(restoreStatus, 120);
          window.setTimeout(restoreStatus, 320);
          for (const delay of [0, 120, 360, 900, 1800]) {
            window.setTimeout(() => {
              remountAfterHistoryRestore(snapshot);
              const active = window.__musixMap;
              if (rendererIsLive(active, document.querySelector("#semantic-map"))) {
                say(statusMessage(payload, currentLod));
              }
            }, delay);
          }
        }
      }, { capture: true });
    })
    .catch(() => say("Interactive map unavailable. The accessible map links remain available."));

  query?.addEventListener("htmx:after:request", () => {
    // Search updates its own results panel and intentionally does not recreate the map.
  });
})();
