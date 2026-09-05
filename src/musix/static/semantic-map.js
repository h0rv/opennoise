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
  // Historical mode returns early before the public-map helpers below, so this
  // shared style accessor has to be initialized before either renderer starts.
  const cssValue = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  let currentLod = -1;
  let selectedNode = null;
  let activeCommunity = null;
  let cameraTransition = false;
  let lodFrame = null;
  let overviewZoom = 1;
  let focusedPositionRestore = new Map();

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

  function initHistoricalMap() {
    let labelFrame = null;
    let resizeFrame = null;
    let selectedId = null;
    let memberRequest = null;
    let drillRequest = null;
    let cy = null;
    // Semantic depth comes only from hierarchy drill actions.  It must never
    // be inferred from camera scale: a wide parent cohort can need a low
    // physical zoom while still being a deep, focused cohort.
    let semanticDepth = 0;
    let currentCohort = null;
    const cohorts = [];
    const style = () => [
      { selector: "node", style: { "background-color": cssValue("--node"), label: "data(displayLabel)", color: cssValue("--ink"), "font-size": 12, "text-outline-color": cssValue("--canvas"), "text-outline-width": 3, "text-valign": "bottom", "text-margin-y": 6, width: 12, height: 12, "overlay-opacity": 0 } },
      { selector: "node:selected", style: { "background-color": cssValue("--focus"), "border-width": 3, "border-color": cssValue("--focus") } },
      { selector: "edge", style: { width: 1.5, "line-color": cssValue("--similarity"), opacity: 0.65 } },
    ];
    const element = (node, position = null, displayLabel = "") => {
      const aggregate = Boolean(node.hierarchy_id);
      const identifier = aggregate ? node.hierarchy_id : node.genre_id;
      return {
      data: { id: `historical-${identifier}`, genreId: aggregate ? node.representative_genre_id : node.genre_id, hierarchyId: node.hierarchy_id ?? null, hierarchyLevel: node.level ?? null, label: node.representative_label ?? node.name, displayLabel, weight: node.member_count ?? node.membership_count, overview: aggregate && Number(node.level) === 0 },
      position: position ?? { x: Number(node.x) * 600, y: Number(node.y) * 600 },
      };
    };
    const elements = (items) => {
      const viewportWidth = Math.max(1, mapElement.clientWidth || window.innerWidth || 1000);
      const viewportHeight = Math.max(1, mapElement.clientHeight || window.innerHeight || 600);
      const aspect = Math.max(0.45, Math.min(3.2, viewportWidth / viewportHeight));
      const width = 600 * aspect;
      const height = 600;
      const isOverview = items.length > 0 && items.every((item) => (
        Boolean(item.hierarchy_id) && Number(item.level) === 0
      ));
      const axis = (key) => items.map((item) => Number(item[key])).filter(Number.isFinite).sort((left, right) => left - right);
      const quantile = (values, fraction) => values.length
        ? values[Math.max(0, Math.min(values.length - 1, Math.round((values.length - 1) * fraction)))]
        : 0;
      const xs = axis("x"); const ys = axis("y");
      const scale = (value, low, high, span) => 0.06 * span + 0.88 * span * (Number(value) - low) / Math.max(high - low, 0.0001);
      const lowX = quantile(xs, 0.05); const highX = quantile(xs, 0.95);
      const lowY = quantile(ys, 0.05); const highY = quantile(ys, 0.95);
      const collapsedX = Math.abs(highX - lowX) < 0.0001;
      const collapsedY = Math.abs(highY - lowY) < 0.0001;
      // Some historical coordinate exports collapse one axis for an aggregate
      // cohort.  Preserve normal coordinates when they have usable spread;
      // otherwise use a stable display-only grid to retain a readable map.
      const ranked = [...items].sort((left, right) => (
        String(left.representative_label ?? left.name).localeCompare(
          String(right.representative_label ?? right.name),
        ) || String(left.hierarchy_id ?? left.genre_id).localeCompare(String(right.hierarchy_id ?? right.genre_id))
      ));
      const ranks = new Map(ranked.map((item, index) => [item, index]));
      const rows = Math.max(2, Math.min(4, Math.ceil(Math.sqrt(items.length))));
      const columns = Math.max(1, Math.ceil(items.length / rows));
      const packed = (index, count, span) => count <= 1
        ? span / 2
        : 0.1 * span + 0.8 * span * index / (count - 1);
      // Overview aggregate coordinates can contain extreme learned outliers,
      // so use a stable landscape grid for the bounded root cohort.  Keep
      // deeper cohorts on their learned coordinates so drilling remains a
      // faithful view of the model output.
      // The root cohort is deliberately a short, landscape reading list, not
      // a projection of 6,291 tiny points. Four columns leave enough screen
      // width for its long umbrella labels at a normal desktop viewport. A
      // phone switches to one column, which guarantees every umbrella name
      // stays readable between the fixed top search and bottom controls.
      const overviewColumns = Math.max(
        1,
        Math.min(items.length, viewportWidth <= 600 ? 1 : 4),
      );
      const overviewRows = Math.ceil(items.length / overviewColumns);
      return items.map((item) => {
        const rank = ranks.get(item) ?? 0;
        if (isOverview) {
          const overviewElement = element(item, {
            x: packed(rank % overviewColumns, overviewColumns, width),
            y: packed(Math.floor(rank / overviewColumns), overviewRows, height),
          }, item.representative_label ?? item.name);
          return overviewElement;
        }
        return element(item, {
          x: collapsedX ? packed(Math.floor(rank / rows), columns, width) : scale(item.x, lowX, highX, width),
          y: collapsedY ? packed(rank % rows, rows, height) : scale(item.y, lowY, highY, height),
        });
      });
    };
    const fitHistoricalViewport = () => {
      const mapBounds = mapElement.getBoundingClientRect();
      const horizontalInset = 120;
      const left = horizontalInset; const right = Math.max(left + 1, mapBounds.width - horizontalInset);
      let top = 0; let bottom = mapBounds.height;
      for (const selector of ["#search", "#map-view-switch", "#map-controls", "#historical-detail"]) {
        const overlay = document.querySelector(selector);
        if (!overlay || getComputedStyle(overlay).display === "none") continue;
        const bounds = overlay.getBoundingClientRect();
        if (bounds.top < mapBounds.top + mapBounds.height / 2) {
          top = Math.max(top, bounds.bottom - mapBounds.top + 32);
        } else if (bounds.bottom > mapBounds.top + mapBounds.height / 2) {
          bottom = Math.min(bottom, bounds.top - mapBounds.top - 32);
        }
      }
      const safeWidth = Math.max(1, right - left); const safeHeight = Math.max(1, bottom - top);
      // Initial overview labels are deliberately present before the first
      // paint. Fit node bodies, not their text bounds, so those labels do not
      // shrink the landscape map into a sparse inset.
      const bounds = cy.nodes().boundingBox({ includeLabels: false });
      const width = Math.max(1, bounds.w); const height = Math.max(1, bounds.h);
      const zoom = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), safeWidth / width, safeHeight / height));
      cy.zoom(zoom);
      cy.pan({
        x: left + (safeWidth - width * zoom) / 2 - bounds.x1 * zoom,
        y: top + (safeHeight - height * zoom) / 2 - bounds.y1 * zoom,
      });
    };
    const setHistoricalLabels = () => {
      // Camera scale is an optional display detail only.  It may reveal a few
      // more labels, but never changes which semantic cohort is rendered.
      const zoomDensity = cy.zoom() < 1 ? 0 : cy.zoom() < 2 ? 1 : 2;
      const renderedFont = mapElement.clientWidth <= 600 ? 13 : 14;
      const renderedNode = mapElement.clientWidth <= 600 ? 11 : 10;
      // Store the model sizes inverse to the camera. This keeps the visible
      // type comfortably readable after fit without inflating it on wide maps.
      const modelFont = Math.max(6, Math.min(24, renderedFont / Math.max(cy.zoom(), 0.01)));
      const modelNode = Math.max(6, Math.min(24, renderedNode / Math.max(cy.zoom(), 0.01)));
      cy.nodes().forEach((node) => node.style({ "font-size": modelFont, width: modelNode, height: modelNode }));
      const baseBudget = mapElement.clientWidth <= 600 ? [18, 28, 42, 64] : [36, 60, 96, 144];
      const budget = Math.min(cy.nodes().length, baseBudget[semanticDepth] + zoomDensity * 8);
      const extent = cy.extent();
      const mapBounds = mapElement.getBoundingClientRect();
      const overlays = ["#search", "#map-controls", "#map-view-switch", "#historical-detail"]
        .map((selector) => document.querySelector(selector))
        .filter((overlay) => overlay && getComputedStyle(overlay).display !== "none")
        .map((overlay) => overlay.getBoundingClientRect());
      const intersects = (first, second) => first.x1 < second.right && first.x2 > second.left
        && first.y1 < second.bottom && first.y2 > second.top;
      const candidates = cy.nodes().filter((node) => {
        const position = node.position();
        return position.x >= extent.x1 && position.x <= extent.x2 && position.y >= extent.y1 && position.y <= extent.y2;
      }).sort((left, right) => Number(right.data("weight")) - Number(left.data("weight")) || String(left.data("label")).localeCompare(String(right.data("label"))));
      const boxes = [];
      let shown = 0;
      cy.nodes().forEach((node) => node.data("displayLabel", ""));
      for (const node of candidates) {
        if (shown === budget) break;
        const position = node.renderedPosition();
        const width = Math.max(40, String(node.data("label")).length * renderedFont * 0.58);
        const box = {
          x1: mapBounds.left + position.x - width / 2, x2: mapBounds.left + position.x + width / 2,
          y1: mapBounds.top + position.y + 8, y2: mapBounds.top + position.y + 8 + renderedFont,
        };
        if (box.x1 < mapBounds.left + 4 || box.x2 > mapBounds.right - 4
          || box.y1 < mapBounds.top + 4 || box.y2 > mapBounds.bottom - 4
          || boxes.some((other) => box.x1 < other.x2 && box.x2 > other.x1 && box.y1 < other.y2 && box.y2 > other.y1)
          || overlays.some((overlay) => intersects(box, overlay))) continue;
        boxes.push(box);
        node.data("displayLabel", node.data("label"));
        shown += 1;
      }
    };
    const scheduleLabels = () => {
      if (labelFrame !== null) return;
      labelFrame = window.requestAnimationFrame(() => {
        labelFrame = null;
        setHistoricalLabels();
      });
    };
    // Wait for the first renderer frame after the map is made visible.  The
    // initial fit happens before Cytoscape has painted its node geometry, so
    // an immediate label pass can see a zero-sized/hidden viewport and leave
    // the overview unlabeled until a resize or camera event occurs.
    const paintInitialHistoricalLabels = () => {
      scheduleLabels();
      window.requestAnimationFrame(() => setHistoricalLabels());
    };
    const updateBackControl = () => {
      const button = document.querySelector('[data-map-action="historical-back"]');
      if (button instanceof HTMLButtonElement) button.disabled = cohorts.length === 0;
    };
    const replaceCohort = (cohort, rememberCurrent = true) => {
      if (rememberCurrent && currentCohort) cohorts.push(currentCohort);
      currentCohort = cohort;
      semanticDepth = cohort.depth;
      selectedId = null;
      cy.elements().remove();
      cy.add(elements(cohort.items));
      fitHistoricalViewport();
      updateBackControl();
      setHistoricalLabels();
      say(`Historical compatibility depth ${semanticDepth}`);
    };
    const restorePreviousCohort = () => {
      drillRequest?.abort();
      drillRequest = null;
      const cohort = cohorts.pop();
      if (!cohort) return false;
      replaceCohort(cohort, false);
      return true;
    };
    const drill = (source, url, depth, property) => {
      drillRequest?.abort();
      const request = new AbortController();
      drillRequest = request;
      fetch(url, { headers: { Accept: "application/json" }, signal: request.signal })
        .then((response) => response.ok ? response.json() : null)
        .then((focused) => {
          // A late response cannot overwrite a Back action or a newer drill.
          if (drillRequest !== request || currentCohort !== source) return;
          const items = focused?.[property] ?? [];
          if (!items.length) return;
          replaceCohort({ depth, items });
        })
        .catch((error) => {
          if (error.name !== "AbortError") say("Historical compatibility drill is unavailable.");
        })
        .finally(() => {
          if (drillRequest === request) drillRequest = null;
        });
    };
    const loadNeighbors = (node) => {
      fetch(`/api/historical-signal-map/neighbors/${encodeURIComponent(node.data("genreId"))}`, { headers: { Accept: "application/json" } })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
          if (!payload) return;
          const additions = (payload.neighbors ?? []).flatMap((edge) => {
            const source = `historical-${edge.genre_id}`;
            const target = `historical-${edge.neighbor_genre_id}`;
            const id = `historical-neighbor-${edge.genre_id}-${edge.neighbor_genre_id}`;
            if (cy.$id(source).empty() || cy.$id(target).empty() || !cy.$id(id).empty()) return [];
            return [{ data: { id, source, target } }];
          });
          if (additions.length) cy.add(additions);
        });
    };
    const loadMembers = (node) => {
      const detail = document.querySelector("#historical-detail");
      if (!detail) return;
      detail.replaceChildren();
      memberRequest?.abort();
      const request = new AbortController();
      memberRequest = request;
      fetch(`/api/historical-signal-map/members/${encodeURIComponent(node.data("genreId"))}`, { headers: { Accept: "application/json" }, signal: request.signal })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
          if (!payload || memberRequest !== request) return;
          const list = document.createElement("ul");
          for (const member of payload.members ?? []) {
            const item = document.createElement("li");
            item.textContent = member.source_artist_name ?? member.source_artist_id;
            list.append(item);
          }
          detail.replaceChildren(list);
        })
        .catch(() => {});
    };
    fetch(graphUrl, { headers: { Accept: "application/json" } })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("historical overview unavailable")))
      .then((payload) => {
        const overview = payload.hierarchy ?? payload.nodes ?? [];
        if (payload.initial_edge_count !== 0 || overview.length > 24) throw new Error("historical overview is not bounded");
        // Cytoscape measures its container as it is constructed. Revealing it
        // first avoids an intermittent zero-sized canvas in headless and
        // slower desktop compositors.
        root.classList.add("js-map-ready");
        try {
          cy = window.cytoscape({ container: mapElement, elements: elements(overview), style: style(), layout: { name: "preset", fit: false }, minZoom: 0.28, maxZoom: 4.8, userPanningEnabled: true, userZoomingEnabled: true, boxSelectionEnabled: false, hideEdgesOnViewport: true, textureOnViewport: true, motionBlur: false, pixelRatio: 1, wheelSensitivity: 0.18 });
        } catch (error) {
          root.classList.remove("js-map-ready");
          throw error;
        }
        window.__musixMap = cy;
        currentCohort = { depth: 0, items: overview };
        // Explicitly center the current model cohort in the rectangle left by
        // fixed search, view-switch, and control overlays.
        cy.resize();
        fitHistoricalViewport();
        window.__musixMapMetrics = {
          initialElementCount: cy.elements().length,
          historical: true,
          get semanticDepth() { return semanticDepth; },
          get cohortCount() { return cohorts.length; },
        };
        mapElement.tabIndex = 0;
        cy.on("zoom pan", scheduleLabels);
        const resizeObserver = new ResizeObserver(() => {
          if (resizeFrame !== null) return;
          resizeFrame = window.requestAnimationFrame(() => {
            resizeFrame = null;
            cy.resize();
            // Repack raw cohort coordinates for the new aspect ratio instead
            // of preserving a desktop-wide world and shrinking labels to fit.
            if (currentCohort) {
              cy.elements().remove();
              cy.add(elements(currentCohort.items));
            }
            fitHistoricalViewport();
            scheduleLabels();
          });
        });
        resizeObserver.observe(mapElement);
        new MutationObserver(() => {
          cy.style(style());
          scheduleLabels();
        }).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
        cy.on("tap", "node", (event) => {
          const hierarchyId = event.target.data("hierarchyId");
          if (hierarchyId && Number(event.target.data("hierarchyLevel")) < 2) {
            const nextLevel = Number(event.target.data("hierarchyLevel")) + 1;
            drill(
              currentCohort,
              `/api/historical-signal-map?level=${nextLevel}&parent_id=${encodeURIComponent(hierarchyId)}`,
              nextLevel,
              "hierarchy",
            );
            return;
          }
          if (hierarchyId) {
            drill(
              currentCohort,
              `/api/historical-signal-map?level=3&parent_id=${encodeURIComponent(hierarchyId)}`,
              3,
              "nodes",
            );
            return;
          }
          cy.$(":selected").unselect();
          event.target.select();
          selectedId = event.target.data("genreId");
          loadNeighbors(event.target);
          loadMembers(event.target);
        });
        document.addEventListener("click", (event) => {
          const button = event.target.closest("[data-map-action]");
          if (!button) return;
          event.preventDefault();
          if (button.dataset.mapAction === "zoom-in") cy.zoom(cy.zoom() * 1.25);
          if (button.dataset.mapAction === "zoom-out") cy.zoom(cy.zoom() / 1.25);
          if (button.dataset.mapAction === "fit") fitHistoricalViewport();
          if (button.dataset.mapAction === "historical-back") {
            restorePreviousCohort();
          }
        }, true);
        mapElement.addEventListener("keydown", (event) => {
          const panStep = Math.max(24, Math.min(mapElement.clientWidth, mapElement.clientHeight) * 0.08);
          const directions = {
            ArrowDown: { x: 0, y: -panStep }, ArrowLeft: { x: panStep, y: 0 },
            ArrowRight: { x: -panStep, y: 0 }, ArrowUp: { x: 0, y: panStep },
          };
          if (directions[event.key]) {
            event.preventDefault();
            cy.panBy(directions[event.key]);
          } else if (["+", "="].includes(event.key)) {
            event.preventDefault();
            cy.zoom({ level: cy.zoom() * 1.25, renderedPosition: { x: mapElement.clientWidth / 2, y: mapElement.clientHeight / 2 } });
          } else if (event.key === "-") {
            event.preventDefault();
            cy.zoom({ level: cy.zoom() / 1.25, renderedPosition: { x: mapElement.clientWidth / 2, y: mapElement.clientHeight / 2 } });
          } else if (event.key === "Escape") {
            if (!restorePreviousCohort()) {
              cy.$(":selected").unselect();
              selectedId = null;
            }
          }
        });
        updateBackControl();
        paintInitialHistoricalLabels();
        // A renderer can still observe an intermediate layout just after the
        // fixed map becomes visible. Re-measure in the first painted frame so
        // every browser gets a correctly sized canvas and fitted overview.
        window.requestAnimationFrame(() => {
          cy.resize();
          fitHistoricalViewport();
          paintInitialHistoricalLabels();
        });
      })
      .catch(() => say("Historical compatibility is unavailable."));
  }

  if (mapElement.dataset.mapMode === "historical") {
    initHistoricalMap();
    return;
  }

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
    // These are graph coordinates, not CSS pixels. A stable wide extent keeps
    // the default from becoming a tall, narrow column when a fitted renderer
    // starts before it has measured the viewport.
    ...mapDimensions(),
  });
  const mapDimensions = () => {
    const viewportWidth = Math.max(1, mapElement.clientWidth || window.innerWidth || 1366);
    const viewportHeight = Math.max(1, mapElement.clientHeight || window.innerHeight || 768);
    // Deliberately keep even a portrait browser's *world* landscape. Cytoscape
    // fits this extent into its canvas; CSS never stretches the graph.
    const aspect = Math.max(1.6, Math.min(2.4, viewportWidth / viewportHeight));
    return { width: 2000 * aspect, height: 2000, aspect };
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
    const horizontalInset = dimensions.width * (mobile ? 0.07 : 0.09);
    const verticalInset = dimensions.height * (mobile ? 0.12 : 0.09);
    const minimumDistance = dimensions.height * (mobile ? 0.10 : 0.085);
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
        overviewNodeSize: Math.round(18 + 14 * overviewProminence(memberCount)),
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
    const overview = cy.nodes(".overview");
    if (overview.empty()) return;
    // Fit the graph's actual wide world into the live canvas.  Do not reset a
    // magic zoom/pan pair: that was the source of the initial narrow layout.
    cy.fit(overview, overviewFitPadding());
    overviewZoom = cy.zoom();
    // The overview is deliberately a landscape world even on a portrait
    // viewport.  Its fitted zoom can therefore be below the desktop floor.
    // Establish the interactive floor *after* that fit, so Cytoscape never
    // clamps the first camera and leaves legitimate overview nodes outside the
    // viewport.  Semantic LODs use overviewZoom relatively, not a magic zoom.
    cy.minZoom(Math.min(0.28, overviewZoom * 0.8));
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
    const overlays = ["#search", "#results", "#map-view-switch", "#layout-lenses", "#map-controls", "#genre-detail"]
      .map((selector) => document.querySelector(selector))
      .filter((element) => element && getComputedStyle(element).display !== "none")
      .map((element) => element.getBoundingClientRect());
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
        if (!inViewport || acceptedBoxes.some((other) => intersects(bounds, other))
          || overlays.some((overlay) => intersects(bounds, {
            x1: overlay.left, y1: overlay.top, x2: overlay.right, y2: overlay.bottom,
          }))) continue;
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
    if (window.__musixMapMetrics) {
      window.__musixMapMetrics.shownLabelCount = accepted;
      window.__musixMapMetrics.labelBudget = overview ? labelBudget(0) : labelBudget(lod);
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
    // Every semantic zoom level has an explicit screen-space target. Leaving
    // level 3 undefined propagates NaN into Cytoscape and falls back to tiny
    // graph-unit text on mobile at the deepest visible level.
    const screenLabelSize = [16, mapElement.clientWidth <= 600 ? 18 : 14, 13, 13][lod];
    // Cytoscape font and node dimensions live in graph coordinates. Scale
    // those values against the fitted camera so overview labels remain legible
    // on screen instead of collapsing to tiny text in a wide internal extent.
    const cameraScale = Math.max(cy.zoom(), 0.01);
    const labelSize = Math.max(8, Math.min(96, screenLabelSize / cameraScale));
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const visible = visibleIds.has(node.data("itemId"));
        node.toggleClass("lod-hidden", !visible);
        node.data(
          "labelSize",
          Boolean(node.data("overview"))
            ? Math.max(8, Math.min(256, overviewFontSize(Number(node.data("weight"))) / cameraScale))
            : labelSize,
        );
        if (Boolean(node.data("overview"))) {
          const screenNodeSize = 22 + 12 * overviewProminence(Number(node.data("weight")));
          node.data("overviewNodeSize", Math.max(12, Math.min(128, screenNodeSize / cameraScale)));
        }
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
    if (mapElement.clientWidth <= 600 && members.length <= 12) {
      // A small community is an explicit semantic cohort. On a narrow screen,
      // display it as a deterministic two-column local grid so every member
      // label has its own readable space. This changes presentation positions
      // only; the source-map coordinates remain the default everywhere else.
      const ordered = members
        .toArray()
        .sort((left, right) => String(left.data("label")).localeCompare(String(right.data("label"))));
      const horizontalSpacing = 360;
      const verticalSpacing = 300;
      focusedPositionRestore = new Map([
        [node.id(), { ...node.position() }],
        ...ordered.map((member) => [member.id(), { ...member.position() }]),
      ]);
      node.position({ x: 0, y: -verticalSpacing });
      ordered.forEach((member, index) => {
        const column = index % 2;
        const row = Math.floor(index / 2);
        member.position({
          x: (column - 0.5) * horizontalSpacing,
          y: row * verticalSpacing,
        });
      });
    }
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
    for (const [id, position] of focusedPositionRestore) cy.$id(id).position(position);
    focusedPositionRestore = new Map();
    activeCommunity = null;
    selectedNode = null;
    cy.$(":selected").unselect();
    // Focus hides non-active overview anchors. Cytoscape ignores display:none
    // nodes when fitting, which otherwise turns the post-drill Fit action into
    // a max-zoom camera on an empty bound. Reveal the full overview before
    // deriving its camera; updateLod immediately restores the intended cohort.
    cy.nodes(".overview").removeClass("lod-hidden");
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

  const initOpenConstructionMap = () => {
    // The open artifact has 6,291 retained nodes, but this renderer never
    // materializes that global set. Each server LOD response is capped at 720.
    let cy = null;
    let baselineZoom = 1;
    let activeLevel = -1;
    let fetching = false;
    const openElement = (node) => ({
      data: {
        id: `open-${node.genre_id}`,
        itemId: node.genre_id,
        label: node.name,
        displayLabel: "",
        labelSize: 13,
        degree: node.degree,
      },
      position: { x: Number(node.x), y: Number(node.y) },
      classes: node.hierarchy_depth === 0 ? "umbrella" : "genre",
    });
    const edgeElement = (edge) => ({
      data: {
        id: `open-${edge.kind}-${edge.source}-${edge.target}`,
        source: `open-${edge.source}`,
        target: `open-${edge.target}`,
        weight: edge.confidence,
      },
      classes: edge.review_candidate ? "similarity" : "taxonomy",
    });
    const paintLabels = () => {
      const visible = cy.nodes().sort((left, right) => Number(right.data("degree")) - Number(left.data("degree"))
        || String(left.data("label")).localeCompare(String(right.data("label"))));
      visible.forEach((node, index) => node.data("displayLabel", index < labelBudget(0) ? node.data("label") : ""));
      window.__musixMapMetrics.shownLabelCount = Math.min(visible.length, labelBudget(0));
    };
    const detail = (node, payload) => {
      const panel = document.querySelector("#open-detail");
      if (panel) panel.textContent = `${node.data("label")}: ${node.data("degree")} public taxonomy or review links.`;
      fetch(`/api/open-construction-map/neighbors/${encodeURIComponent(node.data("itemId"))}`, { headers: { Accept: "application/json" } })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("open graph neighbors unavailable")))
        .then((neighbors) => {
          const additions = neighbors.nodes.filter((item) => cy.$id(`open-${item.genre_id}`).empty()).map(openElement);
          const edges = neighbors.edges.filter((edge) => cy.$id(`open-${edge.kind}-${edge.source}-${edge.target}`).empty()).map(edgeElement);
          if (additions.length || edges.length) cy.batch(() => cy.add([...additions, ...edges]));
          paintLabels();
        })
        .catch(() => say("Open graph detail unavailable."));
    };
    const render = (payload, preserveCamera) => {
      const elements = [
        ...payload.nodes.map(openElement),
        ...payload.edges.map(edgeElement),
      ];
      const previous = preserveCamera && cy ? { zoom: cy.zoom(), pan: cy.pan() } : null;
      cy?.destroy();
      cy = window.cytoscape({
        container: mapElement,
        elements,
        style: stylesheet(),
        layout: { name: "preset", fit: !previous, padding: 72 },
        minZoom: 0.05,
        maxZoom: 4.8,
        userPanningEnabled: true,
        userZoomingEnabled: true,
        boxSelectionEnabled: false,
      });
      if (previous) {
        cy.zoom(previous.zoom);
        cy.pan(previous.pan);
      } else {
        cy.fit(cy.nodes(), 72);
        baselineZoom = cy.zoom();
      }
      activeLevel = payload.level;
      window.__musixMap = cy;
      window.__musixMapMetrics = {
        initialElementCount: cy.elements().length,
        initialNodeCount: cy.nodes().length,
        nodeBudget: payload.node_budget,
        totalNodeCount: payload.total_node_count,
        shownLabelCount: 0,
        labelBudget: labelBudget(0),
      };
      root.classList.add("js-map-ready");
      paintLabels();
      cy.on("tap", "node", (event) => detail(event.target, payload));
      cy.on("zoom", () => {
        const level = Math.min(3, Math.max(0, Math.floor(Math.log2(cy.zoom() / Math.max(baselineZoom, 0.0001)) + 1)));
        if (level !== activeLevel && !fetching) load(level, true);
      });
      cy.on("tap", (event) => {
        if (event.target === cy) cy.$(":selected").unselect();
      });
    };
    const load = (level, preserveCamera = false) => {
      fetching = true;
      fetch(`/api/open-construction-map?level=${level}`, { headers: { Accept: "application/json" } })
        .then((response) => response.ok ? response.json() : Promise.reject(new Error(`open graph request failed: ${response.status}`)))
        .then((payload) => render(payload, preserveCamera))
        .catch(() => say("Open 6,291 landscape unavailable."))
        .finally(() => { fetching = false; });
    };
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-map-action]");
      if (!button || !cy) return;
      const action = button.dataset.mapAction;
      if (action === "zoom-in") cy.zoom(cy.zoom() * 1.25);
      if (action === "zoom-out") cy.zoom(cy.zoom() / 1.25);
      if (action === "fit") cy.fit(cy.nodes(), 72);
    }, true);
    load(0);
  };

  if (mapElement.dataset.mapMode === "open") {
    initOpenConstructionMap();
    return;
  }

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
        // fitOverview establishes the per-viewport floor after it has the
        // actual landscape overview extent.
        minZoom: 0.05,
        maxZoom: 4.8,
        userPanningEnabled: true,
        userZoomingEnabled: true,
        boxSelectionEnabled: false,
      });
      window.__musixMap = cy;
      window.__musixMapMetrics = {
        initialElementCount: cy.elements().length,
        initialNodeCount: cy.nodes().length,
        nodePositionBuilds,
        activeCommunityId: null,
        initialWorldAspect: mapDimensions().aspect,
        nodeBudget: 720,
        shownLabelCount: 0,
        labelBudget: 0,
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
          minZoom: 0.05,
          maxZoom: 4.8,
          userPanningEnabled: true,
          userZoomingEnabled: true,
          boxSelectionEnabled: false,
        });
        window.__musixMap = replacement;
        window.__musixMapMetrics = {
          initialElementCount: replacement.elements().length,
          initialNodeCount: replacement.nodes().length,
          nodePositionBuilds,
          activeCommunityId: null,
          initialWorldAspect: mapDimensions().aspect,
          nodeBudget: 720,
          shownLabelCount: 0,
          labelBudget: 0,
        };
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
