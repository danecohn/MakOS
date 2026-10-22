/* MakBox: the "amerika" colour theme for BeepBox (neon on dark chrome). Derived from BeepBox's own "dark classic"
 * variables at start-up, so upstream themes stay untouched and new upstream variables are inherited. */
(function (root) {
	"use strict";
	const NS = (root.Amerika = root.Amerika || {});
	const OVERRIDES = {
		"--page-margin": "#06050c", "--editor-background": "#0a0814", "--hover-preview": "#ffffff", "--playhead": "#ffb02e",
		"--primary-text": "#f4eeff", "--secondary-text": "#9b92c4", "--inverted-text": "#0a0814", "--text-selection": "rgba(255,61,240,0.55)",
		"--box-selection-fill": "rgba(25,227,255,0.18)", "--loop-accent": "#ff3df0", "--link-accent": "#19e3ff",
		"--ui-widget-background": "#1d1a38", "--ui-widget-focus": "#3a3470", "--pitch-background": "#171433", "--tonic": "#5a3a2a", "--fifth-note": "#1d4560",
		"--white-piano-key": "#d9d9ee", "--black-piano-key": "#2a2750",
	};
	function css() {
		let base = root.beepbox.ColorConfig.themes["dark classic"];
		Object.keys(OVERRIDES).forEach(function (k) {
			const re = new RegExp("(" + k.replace(/[-]/g, "\\-") + "\\s*:)[^;]+;");
			base = re.test(base) ? base.replace(re, "$1 " + OVERRIDES[k] + ";") : base.replace(":root {", ":root {\n\t\t\t\t" + k + ": " + OVERRIDES[k] + ";");
		});
		return base;
	}
	NS.theme = {
		name: "amerika",
		install: function () { root.beepbox.ColorConfig.themes["amerika"] = css(); },
		names: ["amerika", "dark classic", "light classic"],
	};
})(typeof window !== "undefined" ? window : globalThis);
