---
name: Jobcut Design System
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#3e4a3d'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#6e7b6c'
  outline-variant: '#bdcaba'
  surface-tint: '#006e2d'
  primary: '#006b2c'
  on-primary: '#ffffff'
  primary-container: '#00873a'
  on-primary-container: '#f7fff2'
  inverse-primary: '#62df7d'
  secondary: '#904d00'
  on-secondary: '#ffffff'
  secondary-container: '#fe932c'
  on-secondary-container: '#663500'
  tertiary: '#a72d51'
  on-tertiary: '#ffffff'
  tertiary-container: '#c74668'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#7ffc97'
  primary-fixed-dim: '#62df7d'
  on-primary-fixed: '#002109'
  on-primary-fixed-variant: '#005320'
  secondary-fixed: '#ffdcc3'
  secondary-fixed-dim: '#ffb77d'
  on-secondary-fixed: '#2f1500'
  on-secondary-fixed-variant: '#6e3900'
  tertiary-fixed: '#ffd9de'
  tertiary-fixed-dim: '#ffb2bf'
  on-tertiary-fixed: '#3f0016'
  on-tertiary-fixed-variant: '#8a143c'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  container-margin: 24px
  gutter: 16px
---

## Brand & Style

The design system is built on a foundation of **Modern Minimalism** infused with a **Friendly & Approachable** personality. It is designed specifically for the job seeker's journey, aiming to reduce the anxiety of the search through a calm, clear, and encouraging interface. 

The aesthetic prioritizes high legibility and generous whitespace to create a sense of professional ease. By utilizing soft surfaces and a confident primary accent, the UI evokes feelings of growth, reliability, and human-centric support. The tone of the interface is plain-spoken and helpful, removing the friction often found in technical recruitment platforms.

## Colors

The palette is anchored by a soft off-white background to reduce eye strain and provide a "canvas" for pure white surfaces.

- **Primary Green:** Used for main actions, active states, and high-match indicators. It signals progress and success.
- **Amber:** Reserved for mid-range match scores and cautionary states, providing a clear visual bridge between low and high results.
- **Muted Gray:** Used for low-match scores and secondary metadata to de-prioritize less relevant information without sounding negative.
- **Surface & Background:** The distinction between `#F7F8FA` (background) and `#FFFFFF` (surface) is subtle but essential for creating depth through color rather than heavy lines.

## Typography

This design system uses **Inter** for its modern, systematic, yet friendly character. The hierarchy is established through significant size stepping and weight shifts.

- **Headings:** Large and bold to provide clear entry points for the eye. Use `-0.01em` to `-0.02em` letter spacing for larger titles to keep them tight and professional.
- **Body Text:** Set at `16px` for standard readability, with `18px` used for introductory text or "encouraging" messaging blocks.
- **Labels:** Used for metadata, pill chips, and secondary buttons. These are slightly heavier (`500` or `600`) to ensure they remain legible at smaller scales.

## Layout & Spacing

The layout philosophy follows a **Fluid Grid** with generous internal padding to maintain a "calm and obvious" feel.

- **Grid:** A 12-column system for desktop, transitioning to 4 columns on mobile.
- **Whitespace:** Use `xxl` (48px) and `xl` (32px) spacing between major sections to prevent the UI from feeling cluttered.
- **Rhythm:** An 8px linear scale ensures consistent alignment. Component heights should typically be multiples of 8.
- **Mobile Adaptivity:** On mobile, margins reduce to `16px` and headline sizes scale down to ensure content remains the hero.

## Elevation & Depth

This design system utilizes **Tonal Layering** combined with **Ambient Shadows** to define hierarchy.

- **Depth Level 1 (Cards):** Pure white surfaces sit on the off-white background with a soft, diffused shadow: `0px 4px 12px rgba(0, 0, 0, 0.03)`.
- **Depth Level 2 (Modals/Dropdowns):** Higher elevation with a slightly more pronounced shadow to indicate focus: `0px 10px 24px rgba(0, 0, 0, 0.06)`.
- **Interactions:** Hover states on cards should subtly lift (increased shadow) or provide a soft 1px border in the primary color.

## Shapes

The shape language is consistently rounded to reinforce the friendly brand personality.

- **Cards:** Use a fixed `14px` border radius as the primary structural element.
- **Buttons & Inputs:** Use the standard `rounded-md` (8px) for a balanced look.
- **Chips & Scores:** Use **full pill-shaped** or **circular** rounding to distinguish these interactive or status-based elements from structural containers.

## Components

- **Primary Buttons:** High-contrast green (#16A34A) with white text. Use `8px` rounding and `16px` horizontal padding.
- **Pill Chips:** Used for "Remote," "Hybrid," and "On-site." These feature a subtle background tint of the primary color or a soft gray, with `100px` radius.
- **Circular Score Badges:** A perfect circle with a thick stroke or solid fill indicating the match percentage (Green/Amber/Gray). The percentage text sits in the center in a bold weight.
- **Segmented Controls:** Used for toggling views or filters. These should have a subtle gray background with a white "sliding" surface for the active state, maintaining the `8px` or `14px` rounding.
- **Input Fields:** Soft gray borders (#E2E8F0) that transition to the primary green on focus. Labels should be placed above the field in `label-md` style.
- **Cards:** The core container for job listings. Should include generous padding (`24px`) and house the match score in the top-right corner for immediate visibility.
- **Friendly Forms:** Multi-step forms should include progress indicators and encouraging micro-copy (e.g., "Almost there!" or "This helps us find your best match").