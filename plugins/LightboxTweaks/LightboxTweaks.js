(function () {
  // LightboxTweaks
  // CSS handles the overlay layout. JS handles:
  //  1. Toggling .Lightbox-tweaks-fs on fullscreen change
  //  2. Injecting an "Open in Photos" button into the lightbox footer-left
  //     (next to the O-counter button)
  //  3. On click: resolve the current image's file path via GraphQL,
  //     then call the plugin backend to open it in the Windows Photos app

  var PLUGIN_ID = "LightboxTweaks";

  // --- Fullscreen class toggling ---
  function getLightboxEl() {
    return document.querySelector(".Lightbox");
  }

  function updateFullscreenClass() {
    var lb = getLightboxEl();
    if (!lb) return;
    var isFs =
      document.fullscreenElement === lb ||
      document.webkitFullscreenElement === lb;
    if (isFs) {
      lb.classList.add("Lightbox-tweaks-fs");
    } else {
      lb.classList.remove("Lightbox-tweaks-fs");
    }
  }

  document.addEventListener("fullscreenchange", updateFullscreenClass);
  document.addEventListener("webkitfullscreenchange", updateFullscreenClass);

  // --- Prevent click-to-close in fullscreen ---
  // Stash's handleClose closes the lightbox when clicking on the image.
  // In fullscreen, intercept clicks on the capture phase so only the
  // close button (and other header/footer controls) can close the lightbox.
  document.addEventListener(
    "click",
    function (e) {
      var lb = getLightboxEl();
      if (!lb || !lb.classList.contains("Lightbox-tweaks-fs")) return;
      // Check if the click is on a button or link (controls) — allow those
      var target = e.target;
      if (target.closest("button") || target.closest("a")) return;
      // Otherwise, stop the event from reaching Stash's handleClose
      e.stopPropagation();
    },
    true // capture phase: runs before React's onClick
  );

  // --- GraphQL helper ---
  function graphql(query, variables) {
    return fetch("/graphql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query, variables: variables }),
    }).then(function (r) {
      return r.json();
    });
  }

  // --- Get the current image ID from the footer image-link ---
  // The footer-center contains a link: <a href="/images/{id}" class="image-link">
  // This is the most reliable source of the current image ID.
  function getCurrentImageId() {
    var link = document.querySelector(".Lightbox-footer-center .image-link");
    if (!link) {
      console.warn("LightboxTweaks: no .image-link found in footer");
      return null;
    }
    // href is like "/images/123" or "http://localhost:9999/images/123"
    var match = link.getAttribute("href").match(/\/images\/(\d+)/);
    if (match) return match[1];
    console.warn("LightboxTweaks: could not parse image ID from href", link.getAttribute("href"));
    return null;
  }

  // --- Resolve the file path for an image ID via GraphQL ---
  function getImageFilePath(imageId) {
    var query =
      "query GetImageFile($id: ID!) { findImage(id: $id) { id visual_files { ... on ImageFile { path } } } }";
    return graphql(query, { id: imageId }).then(function (res) {
      if (res.errors) {
        throw new Error("GraphQL error: " + res.errors[0].message);
      }
      var image = res.data && res.data.findImage;
      if (!image) {
        throw new Error("Image not found: " + imageId);
      }
      var files = image.visual_files;
      if (files && files.length > 0 && files[0].path) {
        return files[0].path;
      }
      throw new Error("No file path for image " + imageId);
    });
  }

  // --- Call the plugin backend to open the file ---
  function openExternal(path) {
    var query =
      "mutation OpenExternal($plugin_id: ID!, $args: Map!) { runPluginOperation(plugin_id: $plugin_id, args: $args) }";
    return graphql(query, {
      plugin_id: PLUGIN_ID,
      args: { mode: "open_external", path: path },
    }).then(function (res) {
      if (res.errors) {
        throw new Error(res.errors[0].message);
      }
      console.log("LightboxTweaks: openExternal result", res.data);
      return res.data && res.data.runPluginOperation;
    });
  }

  // --- Inject the "Open in Photos" button into the lightbox footer-left ---
  var injectedButton = null;

  function injectButton() {
    var footerLeft = document.querySelector(".Lightbox-footer-left");
    if (!footerLeft) {
      injectedButton = null;
      return;
    }
    if (injectedButton && footerLeft.contains(injectedButton)) return;

    // Only inject if the O-counter is present (i.e. there's a current image)
    var oCounter = footerLeft.querySelector(".o-counter, [class*='o-counter']");
    if (!oCounter) {
      // The O-counter button wrapper is a <div> — check for any button
      var existingBtn = footerLeft.querySelector("button");
      if (!existingBtn) return;
    }

    // Create a wrapper div to match the O-counter's layout
    var wrapper = document.createElement("div");
    wrapper.className = "Lightbox-tweaks-open-wrapper";
    wrapper.style.display = "inline-flex";
    wrapper.style.alignItems = "center";

    var btn = document.createElement("button");
    btn.className = "btn btn-link Lightbox-tweaks-open-btn";
    btn.title = "Open in Photos";
    btn.type = "button";
    btn.style.color = "white";
    btn.style.padding = "0.25rem 0.5rem";
    btn.innerHTML =
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 512 512" fill="currentColor">' +
      '<path d="M0 96C0 60.7 28.7 32 64 32l384 0c35.3 0 64 28.7 64 64l0 320c0 35.3-28.7 64-64 64L64 480c-35.3 0-64-28.7-64-64L0 96zM328 384c-13.3 0-24 10.7-24 24s10.7 24 24 24s24-10.7 24-24s-10.7-24-24-24zm-64-96c-35.3 0-64 28.7-64 64s28.7 64 64 64s64-28.7 64-64s-28.7-64-64-64zm-64-96c-35.3 0-64 28.7-64 64s28.7 64 64 64s64-28.7 64-64s-28.7-64-64-64zM448 208c0-44.2-35.8-80-80-80s-80 35.8-80 80s35.8 80 80 80s80-35.8 80-80z"/>' +
      "</svg>";

    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      console.log("LightboxTweaks: Open in Photos button clicked");

      var imageId = getCurrentImageId();
      if (!imageId) {
        console.error("LightboxTweaks: could not determine current image ID");
        return;
      }
      console.log("LightboxTweaks: current image ID =", imageId);

      btn.style.opacity = "0.4";
      getImageFilePath(imageId)
        .then(function (path) {
          console.log("LightboxTweaks: resolved file path =", path);
          return openExternal(path);
        })
        .then(function (result) {
          console.log("LightboxTweaks: opened successfully", result);
          btn.style.opacity = "1";
        })
        .catch(function (err) {
          console.error("LightboxTweaks: failed to open image:", err);
          btn.style.opacity = "1";
        });
    });

    wrapper.appendChild(btn);

    // The footer-left is a flex column. The O-counter is wrapped in the
    // first <div> child. Insert the button inside that div so it sits
    // next to the O-counter in the same row.
    var oCounterDiv = footerLeft.firstElementChild;
    if (oCounterDiv && oCounterDiv.tagName === "DIV") {
      oCounterDiv.appendChild(wrapper);
    } else {
      // Fallback: just append to footer-left
      footerLeft.appendChild(wrapper);
    }
    injectedButton = wrapper;
  }

  // --- MutationObserver to detect lightbox and inject button ---
  var observer = new MutationObserver(function () {
    updateFullscreenClass();
    injectButton();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // --- Patch RatingStars to allow direct half/fraction star selection ---
  // The original component requires clicking a full star first, then clicking
  // again to toggle the fraction. This patch detects the mouse position within
  // each star so you can click directly on the left half for a half-star, etc.
  if (window.PluginApi && PluginApi.patch && PluginApi.patch.instead) {
    PluginApi.patch.instead("RatingStars", function (props, next) {
      try {
        var React = PluginApi.React;
        var useState = React.useState;
        var Button = PluginApi.libraries.Bootstrap.Button;
        var faStarSolid = PluginApi.libraries.FontAwesomeSolid.faStar;
        var faStarRegular = PluginApi.libraries.FontAwesomeRegular.faStar;
        var FontAwesomeIcon = PluginApi.libraries.ReactFontAwesome.FontAwesomeIcon;
        var Icon = PluginApi.components.Icon;

        // Hooks must be called unconditionally (before any early return)
        var hoverState = useState(undefined);
        var hoverRating = hoverState[0];
        var setHoverRating = hoverState[1];

        // For "full" precision, use the original component
        if (!props.precision || props.precision === "full") {
          return next(props);
        }

        // --- Rating conversion helpers (replicated from src/utils/rating.ts) ---
        function getPrecision(precision) {
          switch (precision) {
            case "half": return 0.5;
            case "quarter": return 0.25;
            case "tenth": return 0.1;
            default: return 1;
          }
        }

        function roundTo(value, step) {
          var inv = 1.0 / step;
          return Math.round(value * inv) / inv;
        }

        function convertToStars(rating100, precision) {
          if (!rating100) return null;
          var p = getPrecision(precision);
          return roundTo(rating100 / 20, p);
        }

        function convertFromStars(stars) {
          return Math.round(stars * 20);
        }

        var precision = getPrecision(props.precision);
        var numSegments = Math.round(1 / precision);
        var disabled = props.disabled || !props.onSetRating;

        var currentRating = convertToStars(props.value, props.precision);
        var stars = currentRating ? Math.floor(currentRating) : 0;
        var fraction = currentRating ? currentRating - stars : 0;

        // Determine which segment the mouse is over within a star
        function getSegmentFromEvent(e) {
          var rect = e.currentTarget.getBoundingClientRect();
          var x = (e.clientX - rect.left) / rect.width;
          if (x < 0) x = 0;
          if (x > 1) x = 1;
          return Math.min(numSegments - 1, Math.floor(x * numSegments));
        }

        function getRatingFromSegment(starIndex, segment) {
          var rating = starIndex - 1 + (segment + 1) / numSegments;
          return roundTo(rating, precision);
        }

        function handleMouseMove(e, starIndex) {
          if (disabled) return;
          var seg = getSegmentFromEvent(e);
          setHoverRating(getRatingFromSegment(starIndex, seg));
        }

        function handleClick(e, starIndex) {
          if (disabled || !props.onSetRating) return;
          var seg = getSegmentFromEvent(e);
          var newRating = getRatingFromSegment(starIndex, seg);

          if (newRating === currentRating && !props.valueRequired) {
            props.onSetRating(null);
          } else {
            props.onSetRating(convertFromStars(newRating));
          }
          setHoverRating(undefined);
        }

        var displayRating = hoverRating !== undefined ? hoverRating : currentRating;
        var displayStars = displayRating ? Math.floor(displayRating) : 0;
        var displayFraction = displayRating ? displayRating - displayStars : 0;

        var max = 5;
        var suffix = props.orMore ? "+" : "";

        function getStarClassName(starIndex) {
          if (hoverRating !== undefined) {
            if (starIndex <= displayStars) return "set";
            return "unset";
          }
          if (stars && stars >= starIndex) return "set";
          return "unset";
        }

        function getFillPercent(starIndex) {
          if (!displayRating) return 0;
          if (starIndex <= displayStars) return 100;
          if (starIndex === displayStars + 1 && displayFraction > 0) {
            return Math.round(displayFraction * 100);
          }
          return 0;
        }

        // Render 5 star buttons using the same Icon + FontAwesomeIcon
        // approach as the original RatingStars component
        var starButtons = [];
        for (var i = 0; i < max; i++) {
          (function (starIndex) {
            var fillPct = getFillPercent(starIndex);
            starButtons.push(
              React.createElement(
                Button,
                {
                  key: "star-" + starIndex,
                  className: "minimal star-fill-" + fillPct,
                  variant: "secondary",
                  disabled: disabled,
                  onMouseMove: function (e) {
                    handleMouseMove(e, starIndex);
                  },
                  onMouseLeave: function () {
                    if (!disabled) setHoverRating(undefined);
                  },
                  onClick: function (e) {
                    handleClick(e, starIndex);
                  },
                  title: displayRating
                    ? (displayRating + suffix).toString()
                    : undefined,
                },
                React.createElement(
                  "div",
                  { className: "filled-star" },
                  React.createElement(FontAwesomeIcon, {
                    icon: faStarSolid,
                    className: "set",
                  })
                ),
                React.createElement(
                  "div",
                  { className: "unfilled-star" },
                  React.createElement(FontAwesomeIcon, {
                    icon: faStarRegular,
                    className: getStarClassName(starIndex),
                  })
                )
              )
            );
          })(i + 1);
        }

        var ratingNumber = "";
        if (displayRating && (displayRating > 0 || displayFraction > 0)) {
          ratingNumber = displayRating + suffix;
        }

        return React.createElement(
          "div",
          {
            className: "rating-stars rating-stars-precision-" + props.precision,
          },
          starButtons,
          React.createElement(
            "span",
            { className: "star-rating-number" },
            ratingNumber
          )
        );
      } catch (err) {
        console.error("LightboxTweaks: RatingStars patch error:", err);
        return next(props);
      }
    });

    console.log("LightboxTweaks: RatingStars patched for direct fraction selection");
  }

  if (window.PluginApi) {
    console.log("LightboxTweaks loaded");
  } else {
    console.warn("LightboxTweaks: window.PluginApi not available yet");
  }
})();
