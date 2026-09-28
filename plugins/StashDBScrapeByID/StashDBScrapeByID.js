(function () {
  // StashDBScrapeByID
  // Adds "Scrape by StashID" to scene pages and a batch action on the scenes list.
  // Uses scrapeSingleScene with { query: stashId } to search StashDB by ID,
  // working around the limitation that "Scrape by fragment" only matches by
  // file fingerprints (phash/oshash/md5), not by stash_id.

  var PLUGIN_ID = "StashDBScrapeByID";

  function init() {
    if (!window.PluginApi) {
      setTimeout(init, 100);
      return;
    }

    var PluginApi = window.PluginApi;
    var React = PluginApi.React;
    var h = React.createElement;
    var useState = React.useState;
    var useEffect = React.useEffect;
    var useRef = React.useRef;
    var useMemo = React.useMemo;

    var Modal = PluginApi.libraries.Bootstrap.Modal;
    var Button = PluginApi.libraries.Bootstrap.Button;
    var Form = PluginApi.libraries.Bootstrap.Form;
    var Badge = PluginApi.libraries.Bootstrap.Badge;

    var FA = PluginApi.libraries.FontAwesomeSolid;
    var FontAwesomeIcon = PluginApi.libraries.ReactFontAwesome.FontAwesomeIcon;

    // --- GraphQL helper ---
    function gql(query, variables) {
      return fetch("/graphql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, variables: variables || {} }),
      }).then(function (r) { return r.json(); });
    }

    // --- Get configured stash-box endpoints ---
    function getStashBoxes() {
      return gql(
        "{ configuration { general { stashBoxes { name endpoint } } } }"
      ).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return (res.data && res.data.configuration &&
          res.data.configuration.general &&
          res.data.configuration.general.stashBoxes) || [];
      });
    }

    // --- Scrape by stash_id query string ---
    var SCRAPE_QUERY =
      "query ScrapeByStashId($source: ScraperSourceInput!, $input: ScrapeSingleSceneInput!) {" +
      "  scrapeSingleScene(source: $source, input: $input) {" +
      "    title code details director date urls" +
      "    studio { name stored_id }" +
      "    performers { name stored_id }" +
      "    tags { name stored_id }" +
      "    remote_site_id image" +
      "  }" +
      "}";

    function scrapeByStashId(endpoint, stashId) {
      return gql(SCRAPE_QUERY, {
        source: { stash_box_endpoint: endpoint },
        input: { query: stashId },
      }).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return (res.data && res.data.scrapeSingleScene) || [];
      });
    }

    // --- Find scenes with stash_id but missing metadata ---
    var FIND_SCENES_QUERY =
      "query FindUndermatchedScenes($filter: FindFilterType, $scene_filter: SceneFilterType) {" +
      "  findScenes(filter: $filter, scene_filter: $scene_filter) {" +
      "    count" +
      "    scenes { id title date stash_ids { stash_id endpoint } performers { id name } tags { id name } }" +
      "  }" +
      "}";

    function findUndermatchedScenes(page, perPage) {
      return gql(FIND_SCENES_QUERY, {
        filter: { per_page: perPage || 100, page: page || 1, sort: "path", direction: "ASC" },
        scene_filter: {
          AND: [
            { stash_id_count: { modifier: "GREATER_THAN", value: 0 } },
            {
              OR: [
                { performer_count: { modifier: "EQUALS", value: 0 } },
                { tag_count: { modifier: "EQUALS", value: 0 } },
              ]
            },
          ]
        },
      }).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return res.data.findScenes;
      });
    }

    // --- Get full scene data for review dialog ---
    var SCENE_QUERY =
      "query GetSceneForReview($id: ID!) {" +
      "  findScene(id: $id) {" +
      "    id title code details director date urls" +
      "    studio { id name }" +
      "    performers { id name }" +
      "    tags { id name }" +
      "    groups { id name }" +
      "    stash_ids { stash_id endpoint }" +
      "  }" +
      "}";

    function getSceneForReview(sceneId) {
      return gql(SCENE_QUERY, { id: sceneId }).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return res.data.findScene;
      });
    }

    // --- Update scene ---
    var UPDATE_SCENE_MUTATION =
      "mutation UpdateScene($input: SceneUpdateInput!) {" +
      "  sceneUpdate(input: $input) { id }" +
      "}";

    function updateScene(input) {
      return gql(UPDATE_SCENE_MUTATION, { input: input }).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return res.data.sceneUpdate;
      });
    }

    // --- Create missing entities ---
    function createPerformer(name) {
      return gql(
        "mutation CreatePerformer($input: PerformerCreateInput!) { performerCreate(input: $input) { id } }",
        { input: { name: name } }
      ).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return res.data.performerCreate.id;
      });
    }

    function createTag(name) {
      return gql(
        "mutation CreateTag($input: TagCreateInput!) { tagCreate(input: $input) { id } }",
        { input: { name: name } }
      ).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return res.data.tagCreate.id;
      });
    }

    function createStudio(name) {
      return gql(
        "mutation CreateStudio($input: StudioCreateInput!) { studioCreate(input: $input) { id } }",
        { input: { name: name } }
      ).then(function (res) {
        if (res.errors) throw new Error(res.errors[0].message);
        return res.data.studioCreate.id;
      });
    }

    // --- Build SceneUpdateInput from selected scraped fields ---
    function buildUpdateInput(sceneId, scraped, selectedFields, createMissing) {
      var input = { id: sceneId };
      var promises = [];

      if (selectedFields.title && scraped.title) input.title = scraped.title;
      if (selectedFields.code && scraped.code) input.code = scraped.code;
      if (selectedFields.details && scraped.details) input.details = scraped.details;
      if (selectedFields.director && scraped.director) input.director = scraped.director;
      if (selectedFields.date && scraped.date) input.date = scraped.date;
      if (selectedFields.urls && scraped.urls) input.urls = scraped.urls;

      if (selectedFields.studio && scraped.studio) {
        if (scraped.studio.stored_id) {
          input.studio_id = scraped.studio.stored_id;
        } else if (createMissing && scraped.studio.name) {
          promises.push(
            createStudio(scraped.studio.name).then(function (id) {
              input.studio_id = id;
            })
          );
        }
      }

      if (selectedFields.performers && scraped.performers) {
        var performerIds = [];
        var missingPerformers = [];
        scraped.performers.forEach(function (p) {
          if (p.stored_id) {
            performerIds.push(p.stored_id);
          } else if (p.name) {
            missingPerformers.push(p);
          }
        });
        if (createMissing) {
          missingPerformers.forEach(function (p) {
            promises.push(
              createPerformer(p.name).then(function (id) {
                performerIds.push(id);
              })
            );
          });
        }
        if (performerIds.length || !createMissing) {
          input.performer_ids = performerIds;
        }
      }

      if (selectedFields.tags && scraped.tags) {
        var tagIds = [];
        var missingTags = [];
        scraped.tags.forEach(function (t) {
          if (t.stored_id) {
            tagIds.push(t.stored_id);
          } else if (t.name) {
            missingTags.push(t);
          }
        });
        if (createMissing) {
          missingTags.forEach(function (t) {
            promises.push(
              createTag(t.name).then(function (id) {
                tagIds.push(id);
              })
            );
          });
        }
        if (tagIds.length || !createMissing) {
          input.tag_ids = tagIds;
        }
      }

      return Promise.all(promises).then(function () { return input; });
    }

    // --- Format values for display ---
    function formatValue(val) {
      if (!val) return "(empty)";
      if (Array.isArray(val)) {
        if (val.length === 0) return "(empty)";
        return val.map(function (v) {
          if (typeof v === "object") return v.name || JSON.stringify(v);
          return v;
        }).join(", ");
      }
      if (typeof val === "object") return val.name || JSON.stringify(val);
      if (typeof val === "string" && val.length > 80) return val.substring(0, 77) + "...";
      return String(val);
    }

    // --- Field definitions for review dialog ---
    var SCRAPE_FIELDS = [
      { key: "title", label: "Title", type: "text" },
      { key: "code", label: "Code", type: "text" },
      { key: "date", label: "Date", type: "text" },
      { key: "director", label: "Director", type: "text" },
      { key: "details", label: "Details", type: "text" },
      { key: "urls", label: "URLs", type: "list" },
      { key: "studio", label: "Studio", type: "object" },
      { key: "performers", label: "Performers", type: "list" },
      { key: "tags", label: "Tags", type: "list" },
    ];

    // --- Review Dialog Component ---
    function ReviewDialog(props) {
      // props: { scraped, currentScene, onApply, onClose }
      var scraped = props.scraped;
      var current = props.currentScene;

      var initialState = {};
      SCRAPE_FIELDS.forEach(function (f) {
        // Default: select scraped value if current is empty, otherwise leave unchecked
        var hasScraped = scraped && scraped[f.key];
        var hasCurrent = current && current[f.key];
        initialState[f.key] = hasScraped && !hasCurrent;
      });

      var state = useState(initialState);
      var selected = state[0];
      var setSelected = state[1];

      var createMissingState = useState(true);
      var createMissing = createMissingState[0];
      var setCreateMissing = createMissingState[1];

      var applyingState = useState(false);
      var applying = applyingState[0];
      var setApplying = applyingState[1];

      function toggleField(key) {
        var next = Object.assign({}, selected);
        next[key] = !next[key];
        setSelected(next);
      }

      function handleApply() {
        setApplying(true);
        buildUpdateInput(current.id, scraped, selected, createMissing)
          .then(function (input) {
            return updateScene(input);
          })
          .then(function () {
            setApplying(false);
            props.onApply();
          })
          .catch(function (err) {
            setApplying(false);
            console.error(PLUGIN_ID + ": apply error:", err);
            alert("Failed to update scene: " + err.message);
          });
      }

      var rows = SCRAPE_FIELDS.map(function (f) {
        var currentVal = current && current[f.key];
        var scrapedVal = scraped && scraped[f.key];
        var hasScraped = scrapedVal != null && scrapedVal !== "";
        if (!hasScraped) return null;

        // Check for missing entities (stored_id is null)
        var missingNote = "";
        if (f.type === "list" && Array.isArray(scrapedVal)) {
          var missing = scrapedVal.filter(function (v) { return !v.stored_id; });
          if (missing.length > 0) {
            missingNote = " (" + missing.length + " new)";
          }
        } else if (f.type === "object" && scrapedVal && !scrapedVal.stored_id) {
          missingNote = " (new)";
        }

        return h(
          "tr",
          { key: f.key, className: "sbsid-review-row" },
          h("td", { className: "sbsid-review-label" },
            h(Form.Check, {
              type: "checkbox",
              label: f.label,
              checked: !!selected[f.key],
              onChange: function () { toggleField(f.key); },
            })
          ),
          h("td", { className: "sbsid-review-current" }, formatValue(currentVal)),
          h("td", { className: "sbsid-review-arrow" }, "\u2192"),
          h("td", { className: "sbsid-review-scraped" },
            formatValue(scrapedVal),
            missingNote ? h("span", { className: "sbsid-missing-note" }, missingNote) : null
          )
        );
      });

      var hasAnySelected = false;
      for (var k in selected) {
        if (selected[k]) { hasAnySelected = true; break; }
      }

      return h(Modal, {
        show: true,
        onHide: props.onClose,
        size: "lg",
        className: "sbsid-review-modal",
      },
        h(Modal.Header, { closeButton: true },
          h(Modal.Title, null,
            "Review Scraped Metadata",
            h("span", { className: "sbsid-scene-id" }, " Scene #" + current.id)
          )
        ),
        h(Modal.Body, null,
          h("table", { className: "sbsid-review-table" },
            h("thead", null,
              h("tr", null,
                h("th", null, "Field"),
                h("th", null, "Current"),
                h("th", null, ""),
                h("th", null, "Scraped")
              )
            ),
            h("tbody", null, rows)
          ),
          h("div", { className: "sbsid-create-missing" },
            h(Form.Check, {
              type: "checkbox",
              label: "Create missing performers/tags/studios",
              checked: createMissing,
              onChange: function () { setCreateMissing(!createMissing); },
            })
          )
        ),
        h(Modal.Footer, null,
          h(Button, { variant: "secondary", onClick: props.onClose }, "Cancel"),
          h(Button, {
            variant: "primary",
            onClick: handleApply,
            disabled: !hasAnySelected || applying,
          }, applying ? "Applying..." : "Apply Selected")
        )
      );
    }

    // --- Scrape Button Component (per scene) ---
    function ScrapeByIDButton(props) {
      // props: { scene }
      var scene = props.scene;
      var stashIds = (scene && scene.stash_ids) || [];

      var modalState = useState(null);
      var modal = modalState[0];
      var setModal = modalState[1];

      var loadingState = useState(false);
      var loading = loadingState[0];
      var setLoading = loadingState[1];

      var boxesState = useState([]);
      var boxes = boxesState[0];
      var setBoxes = boxesState[1];

      var showMenuState = useState(false);
      var showMenu = showMenuState[0];
      var setShowMenu = showMenuState[1];

      useEffect(function () {
        getStashBoxes().then(setBoxes).catch(function (e) {
          console.error(PLUGIN_ID + ": failed to get stash boxes:", e);
        });
      }, []);

      if (stashIds.length === 0) return null;

      function doScrape(endpoint, stashId) {
        setShowMenu(false);
        setLoading(true);
        scrapeByStashId(endpoint, stashId)
          .then(function (results) {
            setLoading(false);
            if (!results || results.length === 0) {
              alert("No scenes found on StashDB for ID: " + stashId);
              return;
            }
            // Use first result
            var scraped = results[0];
            // Build current scene object from props
            var current = {
              id: scene.id,
              title: scene.title,
              code: scene.code,
              date: scene.date,
              director: scene.director,
              details: scene.details,
              urls: scene.urls,
              studio: scene.studio,
              performers: scene.performers,
              tags: scene.tags,
            };
            setModal({ scraped: scraped, current: current });
          })
          .catch(function (err) {
            setLoading(false);
            console.error(PLUGIN_ID + ": scrape error:", err);
            alert("Scrape failed: " + err.message);
          });
      }

      // Build dropdown items for each stash_id + endpoint combo
      var menuItems = [];
      stashIds.forEach(function (sid, i) {
        var box = null;
        if (sid.endpoint) {
          box = boxes.find(function (b) { return b.endpoint === sid.endpoint; });
        }
        var boxName = box ? box.name : (sid.endpoint || "StashDB #" + (i + 1));
        var endpoint = box ? box.endpoint : sid.endpoint;

        menuItems.push(
          h("div", {
            key: "sid-" + i,
            className: "sbsid-menu-item",
            onClick: function () { doScrape(endpoint, sid.stash_id); },
          },
            h(FontAwesomeIcon, { icon: FA.faCloudDownloadAlt, className: "sbsid-menu-icon" }),
            h("span", null, boxName),
            h("span", { className: "sbsid-menu-stashid" }, sid.stash_id.substring(0, 8) + "...")
          )
        );
      });

      // If only one stash_id and one box, skip the dropdown
      var buttonOnClick;
      if (stashIds.length === 1 && boxes.length <= 1) {
        var sid = stashIds[0];
        var endpoint = boxes.length === 1 ? boxes[0].endpoint : sid.endpoint;
        buttonOnClick = function () { doScrape(endpoint, sid.stash_id); };
      } else {
        buttonOnClick = function () { setShowMenu(!showMenu); };
      }

      return h("div", { className: "sbsid-scene-button-wrapper" },
        h(Button, {
          variant: "primary",
          size: "sm",
          className: "sbsid-scrape-btn",
          onClick: buttonOnClick,
          disabled: loading,
        },
          loading
            ? h(FontAwesomeIcon, { icon: FA.faSpinner, spin: true })
            : h(FontAwesomeIcon, { icon: FA.faCloudDownloadAlt }),
          " Scrape by StashID"
        ),
        showMenu
          ? h("div", { className: "sbsid-dropdown" }, menuItems)
          : null,
        modal
          ? h(ReviewDialog, {
              scraped: modal.scraped,
              currentScene: modal.current,
              onClose: function () { setModal(null); },
              onApply: function () {
                setModal(null);
                // Reload page to reflect changes
                if (window.location) window.location.reload();
              },
            })
          : null
      );
    }

    // --- Batch Scrape Modal ---
    function BatchScrapeModal(props) {
      // props: { onClose }
      var stepState = useState("config"); // config -> scanning -> scraping -> done
      var step = stepState[0];
      var setStep = stepState[1];

      var scenesState = useState([]);
      var scenes = scenesState[0];
      var setScenes = scenesState[1];

      var progressState = useState({ current: 0, total: 0, status: "" });
      var progress = progressState[0];
      var setProgress = progressState[1];

      var resultsState = useState([]);
      var results = resultsState[0];
      var setResults = resultsState[1];

      var boxesState = useState([]);
      var boxes = boxesState[0];
      var setBoxes = boxesState[1];

      var selectedEndpointState = useState("");
      var selectedEndpoint = selectedEndpointState[0];
      var setSelectedEndpoint = selectedEndpointState[1];

      var reviewState = useState(null);
      var reviewScene = reviewState[0];
      var setReviewScene = reviewState[1];

      var autoApplyState = useState(false);
      var autoApply = autoApplyState[0];
      var setAutoApply = autoApplyState[1];

      var createMissingState = useState(true);
      var createMissing = createMissingState[0];
      var setCreateMissing = createMissingState[1];

      var stopFlag = useRef(false);

      useEffect(function () {
        getStashBoxes().then(function (b) {
          setBoxes(b);
          if (b.length > 0) setSelectedEndpoint(b[0].endpoint);
        }).catch(function (e) {
          console.error(PLUGIN_ID + ": failed to get stash boxes:", e);
        });
      }, []);

      function startScan() {
        setStep("scanning");
        setProgress({ current: 0, total: 0, status: "Searching for scenes with StashID but missing metadata..." });

        var allScenes = [];
        var page = 1;
        var perPage = 200;

        function fetchPage() {
          return findUndermatchedScenes(page, perPage).then(function (data) {
            allScenes = allScenes.concat(data.scenes);
            setProgress({ current: allScenes.length, total: data.count, status: "Found " + allScenes.length + " / " + data.count + " scenes" });

            if (allScenes.length < data.count && page * perPage < data.count && !stopFlag.current) {
              page++;
              return fetchPage();
            }
            return allScenes;
          });
        }

        fetchPage().then(function (found) {
          setScenes(found);
          setStep("scraping");
          startScraping(found);
        }).catch(function (err) {
          console.error(PLUGIN_ID + ": scan error:", err);
          setProgress({ current: 0, total: 0, status: "Error: " + err.message });
          setStep("config");
        });
      }

      function startScraping(targetScenes) {
        var scrapeResults = [];
        var i = 0;

        function scrapeNext() {
          if (stopFlag.current) {
            setStep("done");
            return;
          }
          if (i >= targetScenes.length) {
            setStep("done");
            setProgress({ current: targetScenes.length, total: targetScenes.length, status: "Complete" });
            return;
          }

          var scene = targetScenes[i];
          var stashId = scene.stash_ids && scene.stash_ids[0] && scene.stash_ids[0].stash_id;

          if (!stashId) {
            i++;
            return scrapeNext();
          }

          setProgress({ current: i + 1, total: targetScenes.length, status: "Scraping: " + (scene.title || scene.id) });

          scrapeByStashId(selectedEndpoint, stashId)
            .then(function (scraped) {
              if (scraped && scraped.length > 0) {
                var result = {
                  scene: scene,
                  scraped: scraped[0],
                  status: "found",
                };
                scrapeResults.push(result);

                if (autoApply) {
                  // Auto-apply: only fill empty fields
                  var selectedFields = {};
                  SCRAPE_FIELDS.forEach(function (f) {
                    var hasCurrent = scene && scene[f.key];
                    var hasScraped = scraped[0] && scraped[0][f.key];
                    selectedFields[f.key] = hasScraped && !hasCurrent;
                  });

                  return buildUpdateInput(scene.id, scraped[0], selectedFields, createMissing)
                    .then(function (input) {
                      // Only update if there's something to apply
                      var hasFields = Object.keys(input).length > 1; // more than just 'id'
                      if (hasFields) {
                        return updateScene(input).then(function () {
                          result.status = "applied";
                          setResults(scrapeResults.slice());
                        });
                      }
                    });
                } else {
                  setResults(scrapeResults.slice());
                }
              } else {
                scrapeResults.push({ scene: scene, scraped: null, status: "no match" });
                setResults(scrapeResults.slice());
              }
            })
            .catch(function (err) {
              scrapeResults.push({ scene: scene, scraped: null, status: "error: " + err.message });
              setResults(scrapeResults.slice());
            })
            .then(function () {
              i++;
              scrapeNext();
            });
        }

        scrapeNext();
      }

      function handleStop() {
        stopFlag.current = true;
      }

      function reviewResult(result) {
        getSceneForReview(result.scene.id).then(function (current) {
          setReviewScene({ scraped: result.scraped, current: current });
        });
      }

      // --- Render ---
      var body = null;

      if (step === "config") {
        var endpointOptions = boxes.map(function (b, i) {
          return h("option", { key: i, value: b.endpoint }, b.name || ("StashDB #" + (i + 1)));
        });

        body = h("div", { className: "sbsid-batch-config" },
          h("p", null, "This will find all scenes that have a StashDB ID but are missing performers or tags, then scrape each one using the StashID as the query string."),
          h(Form.Group, null,
            h(Form.Label, null, "StashDB Endpoint"),
            h(Form.Control, {
              as: "select",
              value: selectedEndpoint,
              onChange: function (e) { setSelectedEndpoint(e.target.value); },
            }, endpointOptions)
          ),
          h(Form.Group, null,
            h(Form.Check, {
              type: "checkbox",
              label: "Auto-apply (only fill empty fields, no review dialog)",
              checked: autoApply,
              onChange: function () { setAutoApply(!autoApply); },
            })
          ),
          h(Form.Group, null,
            h(Form.Check, {
              type: "checkbox",
              label: "Create missing performers/tags/studios",
              checked: createMissing,
              onChange: function () { setCreateMissing(!createMissing); },
            })
          ),
          h("div", { className: "sbsid-batch-actions" },
            h(Button, {
              variant: "primary",
              onClick: startScan,
              disabled: !selectedEndpoint,
            }, "Start")
          )
        );
      } else if (step === "scanning" || step === "scraping") {
        var pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
        body = h("div", { className: "sbsid-batch-progress" },
          h("p", null, progress.status),
          h("div", { className: "sbsid-progress-bar" },
            h("div", { className: "sbsid-progress-fill", style: { width: pct + "%" } })
          ),
          h("p", null, progress.current + " / " + progress.total),
          step === "scraping"
            ? h(Button, { variant: "danger", size: "sm", onClick: handleStop }, "Stop")
            : null
        );
      } else if (step === "done") {
        var resultRows = results.map(function (r, i) {
          var statusBadge;
          if (r.status === "found") statusBadge = h(Badge, { variant: "warning" }, "Found - Review");
          else if (r.status === "applied") statusBadge = h(Badge, { variant: "success" }, "Applied");
          else if (r.status === "no match") statusBadge = h(Badge, { variant: "secondary" }, "No match");
          else statusBadge = h(Badge, { variant: "danger" }, r.status);

          return h("tr", { key: i },
            h("td", null, r.scene.title || r.scene.id),
            h("td", null,
              r.scene.performers ? r.scene.performers.length : 0, " / ",
              r.scene.tags ? r.scene.tags.length : 0
            ),
            h("td", null, statusBadge),
            h("td", null,
              r.status === "found" && !autoApply
                ? h(Button, {
                    size: "sm",
                    variant: "outline-primary",
                    onClick: function () { reviewResult(r); },
                  }, "Review")
                : null
            )
          );
        });

        body = h("div", { className: "sbsid-batch-results" },
          h("p", null,
            "Scraped " + results.length + " scenes. ",
            results.filter(function (r) { return r.status === "applied"; }).length, " applied, ",
            results.filter(function (r) { return r.status === "found"; }).length, " pending review, ",
            results.filter(function (r) { return r.status === "no match"; }).length, " no match."
          ),
          results.length > 0
            ? h("table", { className: "sbsid-results-table" },
                h("thead", null,
                  h("tr", null,
                    h("th", null, "Scene"),
                    h("th", null, "P/T"),
                    h("th", null, "Status"),
                    h("th", null, "")
                  )
                ),
                h("tbody", null, resultRows)
              )
            : null,
          h("div", { className: "sbsid-batch-actions" },
            h(Button, { variant: "secondary", onClick: function () { setStep("config"); setResults([]); stopFlag.current = false; } }, "Back"),
            h(Button, { variant: "primary", onClick: props.onClose }, "Close")
          )
        );
      }

      return h(Modal, {
        show: true,
        onHide: props.onClose,
        size: "lg",
        className: "sbsid-batch-modal",
      },
        h(Modal.Header, { closeButton: true },
          h(Modal.Title, null, "Batch Scrape by StashID")
        ),
        h(Modal.Body, null, body),
        reviewScene
          ? h(ReviewDialog, {
              scraped: reviewScene.scraped,
              currentScene: reviewScene.current,
              onClose: function () { setReviewScene(null); },
              onApply: function () {
                setReviewScene(null);
                // Mark as applied in results
                setResults(results.map(function (r) {
                  if (r.scene.id === reviewScene.current.id) {
                    return Object.assign({}, r, { status: "applied" });
                  }
                  return r;
                }));
              },
            })
          : null
      );
    }

    // --- Batch Button Component (for scenes list) ---
    function BatchButton() {
      var showState = useState(false);
      var show = showState[0];
      var setShow = showState[1];

      return h("div", { className: "sbsid-batch-button-wrapper" },
        h(Button, {
          variant: "outline-secondary",
          size: "sm",
          className: "sbsid-batch-btn",
          onClick: function () { setShow(true); },
        },
          h(FontAwesomeIcon, { icon: FA.faCloudDownloadAlt }),
          " Batch Scrape by StashID"
        ),
        show
          ? h(BatchScrapeModal, { onClose: function () { setShow(false); } })
          : null
      );
    }

    // --- Patch ScenePage: add per-scene Scrape by StashID button ---
    // DISABLED: causes React error #31 on some scene pages. Needs investigation.
    // PluginApi.patch.after("ScenePage", function (props, result) {
    //   if (result === null || result === undefined || (typeof result === "object" && !Array.isArray(result) && !React.isValidElement(result))) return result;
    //   if (!props || !props.scene) return result;
    //   var stashIds = props.scene.stash_ids;
    //   if (!stashIds || stashIds.length === 0) return result;
    //
    //   return h(React.Fragment, null,
    //     result,
    //     h(ScrapeByIDButton, { scene: props.scene })
    //   );
    // });

    // --- Patch FilteredSceneList: add batch button ---
    // DISABLED: This patch causes React error #31 on Studio/Performer pages
    // because FilteredSceneList is a shared component. Re-enabling requires
    // a different patch point or a more targeted approach.
    // PluginApi.patch.after("FilteredSceneList", function (props, result) {
    //   if (!window.location.pathname.startsWith("/scenes")) return result;
    //   if (result === null || result === undefined || typeof result === "object" && !Array.isArray(result) && !React.isValidElement(result)) return result;
    //
    //   return h(React.Fragment, null,
    //     result,
    //     h(BatchButton, null)
    //   );
    // });

    console.log(PLUGIN_ID + " loaded");
  }

  init();
})();
