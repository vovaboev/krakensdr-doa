import '@vaadin/polymer-legacy-adapter/style-modules.js';
import '@vaadin/combo-box/theme/lumo/vaadin-combo-box.js';
import 'Frontend/generated/jar-resources/flow-component-renderer.js';
import 'Frontend/generated/jar-resources/comboBoxConnector.js';
import '@vaadin/tooltip/theme/lumo/vaadin-tooltip.js';
import '@vaadin/progress-bar/theme/lumo/vaadin-progress-bar.js';
import '@vaadin/button/theme/lumo/vaadin-button.js';
import 'Frontend/generated/jar-resources/buttonFunctions.js';
import '@vaadin/vertical-layout/theme/lumo/vaadin-vertical-layout.js';
import '@vaadin/horizontal-layout/theme/lumo/vaadin-horizontal-layout.js';
import '@vaadin/confirm-dialog/theme/lumo/vaadin-confirm-dialog.js';
import '@vaadin/multi-select-combo-box/theme/lumo/vaadin-multi-select-combo-box.js';
import '@vaadin/text-field/theme/lumo/vaadin-text-field.js';
import '@vaadin/notification/theme/lumo/vaadin-notification.js';
import '@vaadin/radio-group/theme/lumo/vaadin-radio-group.js';
import '@vaadin/list-box/theme/lumo/vaadin-list-box.js';
import '@vaadin/radio-group/theme/lumo/vaadin-radio-button.js';
import '@vaadin/tabs/theme/lumo/vaadin-tab.js';
import '@vaadin/checkbox-group/theme/lumo/vaadin-checkbox-group.js';
import '@vaadin/grid/theme/lumo/vaadin-grid-column-group.js';
import '@vaadin/grid/theme/lumo/vaadin-grid.js';
import '@vaadin/grid/theme/lumo/vaadin-grid-column.js';
import '@vaadin/grid/theme/lumo/vaadin-grid-sorter.js';
import '@vaadin/checkbox/theme/lumo/vaadin-checkbox.js';
import 'Frontend/generated/jar-resources/gridConnector.ts';
import '@vaadin/time-picker/theme/lumo/vaadin-time-picker.js';
import 'Frontend/generated/jar-resources/vaadin-time-picker/timepickerConnector.js';
import '@vaadin/side-nav/theme/lumo/vaadin-side-nav.js';
import 'Frontend/generated/jar-resources/vaadin-grid-flow-selection-column.js';
import '@vaadin/virtual-list/theme/lumo/vaadin-virtual-list.js';
import 'Frontend/generated/jar-resources/virtualListConnector.js';
import '@vaadin/item/theme/lumo/vaadin-item.js';
import 'Frontend/generated/jar-resources/menubarConnector.js';
import '@vaadin/menu-bar/theme/lumo/vaadin-menu-bar.js';
import '@vaadin/dialog/theme/lumo/vaadin-dialog.js';
import '@vaadin/integer-field/theme/lumo/vaadin-integer-field.js';
import '@vaadin/password-field/theme/lumo/vaadin-password-field.js';
import '@vaadin/email-field/theme/lumo/vaadin-email-field.js';
import '@vaadin/side-nav/theme/lumo/vaadin-side-nav-item.js';
import '@vaadin/context-menu/theme/lumo/vaadin-context-menu.js';
import 'Frontend/generated/jar-resources/contextMenuConnector.js';
import 'Frontend/generated/jar-resources/contextMenuTargetConnector.js';
import '@vaadin/number-field/theme/lumo/vaadin-number-field.js';
import '@vaadin/date-picker/theme/lumo/vaadin-date-picker.js';
import 'Frontend/generated/jar-resources/datepickerConnector.js';
import '@vaadin/text-area/theme/lumo/vaadin-text-area.js';
import '@vaadin/date-time-picker/theme/lumo/vaadin-date-time-picker.js';
import '@vaadin/tabs/theme/lumo/vaadin-tabs.js';
import '@vaadin/select/theme/lumo/vaadin-select.js';
import 'Frontend/generated/jar-resources/selectConnector.js';
import 'Frontend/generated/jar-resources/lit-renderer.ts';
import '@vaadin/common-frontend/ConnectionIndicator.js';
import '@vaadin/vaadin-lumo-styles/color-global.js';
import '@vaadin/vaadin-lumo-styles/typography-global.js';
import '@vaadin/vaadin-lumo-styles/sizing.js';
import '@vaadin/vaadin-lumo-styles/spacing.js';
import '@vaadin/vaadin-lumo-styles/style.js';
import '@vaadin/vaadin-lumo-styles/vaadin-iconset.js';
import 'Frontend/generated/jar-resources/ReactRouterOutletElement.tsx';

const loadOnDemand = (key) => {
  const pending = [];
  if (key === 'f052b325001897ce3bbf0d48579d4bee7241da0787e1195873bdd391adbe3bae') {
    pending.push(import('./chunks/chunk-80e7ef00db7958992b70e0700d465adb4d91e63c0d005ce7b98887e2ac91ab42.js'));
  }
  if (key === 'b89c59db7d83208e9116b5c39b53c8731fac65ef567ee29f93d204bfe188c9bf') {
    pending.push(import('./chunks/chunk-1b34b9c487ccc99a7208f6020bec490100dd8c6edc886082f60296134f9b8363.js'));
  }
  if (key === '7fb4b633cf1325b6f1f6995f9819c08721f1f8fa0c4993c1ef1af41ebedbf0b5') {
    pending.push(import('./chunks/chunk-c4cec496c374786ec3247067c08e530e97d6ec2c88b4c62b84a20533d2f78a93.js'));
  }
  return Promise.all(pending);
}

window.Vaadin = window.Vaadin || {};
window.Vaadin.Flow = window.Vaadin.Flow || {};
window.Vaadin.Flow.loadOnDemand = loadOnDemand;
window.Vaadin.Flow.resetFocus = () => {
 let ae=document.activeElement;
 while(ae&&ae.shadowRoot) ae = ae.shadowRoot.activeElement;
 return !ae || ae.blur() || ae.focus() || true;
}