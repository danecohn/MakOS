# Artemis Cloud interface specification

Artemis Softworks LLC · Founder: Demetria Althea Cohn.

The supplied iCloud web archive was studied privately as a visual and interaction reference. No account content, archived application code, Apple artwork, font binaries, or service credentials are included. The archive contains HTML, CSS and compiled JavaScript, not original TypeScript sources. Implementations here are original adaptations using each application's existing framework.

## Interface principles

- Bright atmospheric blue behind quiet white workspace surfaces. Preserve each product's own identity and the Artemis crescent-and-bow publisher mark.
- System typography, readable 14–17px body text, 20–28px card headings, 40–64px page headings. Use platform fonts without redistributing proprietary fonts.
- Centered dashboards around 1040–1120px; responsive tiles, 20–24px spacing, 20–24px corners. Productive editors retain compact controls and their canvas layouts.
- Translucent toolbars; restrained shadows; consistent saturated blue actions. Brass stays in the original publisher artwork.
- Touch controls at least 44px, inputs 16px on mobile, safe-area navigation and stacked cards. Keyboard focus remains visible; respect reduced motion. Do not add decorative drag/reorder affordances without a working implementation.
- Preserve saved data, authentication, account routes, preferences, accessibility and upstream licenses. Native palettes adapt the same hierarchy to Qt, React Native, GTK and editor theme formats.

`moonrise.css` remains the compatibility filename for shared design tokens. Applications consume equivalent tokens in their native stylesheets. Apple service data continues to be handled by Apple; family shortcuts and notes remain local unless a product already supports account sync.
