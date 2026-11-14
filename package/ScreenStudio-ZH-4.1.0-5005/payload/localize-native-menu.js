/* Local display-only translation for Screen Studio's custom native menus. */
const dictionary = __SCREEN_STUDIO_NATIVE_MENU_DICTIONARY__;
const normalize = text => text.replace(/\u00a0/g, ' ').replace(/…/g, '...');
const exact = new Map(Object.entries(dictionary).map(([from, to]) => [normalize(from.trim()), to.trim()]));
const displayFields = ['label', 'sublabel', 'toolTip', 'description', 'valueLabel', 'badge'];
const collectionFields = ['items', 'submenu', 'options'];
// Native menu items for applications/windows carry fileIconPath. Respect other
// explicit identity metadata too, without traversing or changing their values.
const identityFields = ['fileIconPath', 'filePath', 'projectPath', 'deviceId', 'bundleId', 'appPath'];

function translateDisplay(text) {
  if (typeof text !== 'string') return text;
  if (Object.hasOwn(dictionary, text)) return dictionary[text];
  const trimmed = text.trim();
  const replacement = exact.get(normalize(trimmed));
  if (replacement !== undefined) return text.replace(trimmed, replacement);
  // These two known UI messages append version/duration values. Do not apply
  // arbitrary dictionary prefixes to user/device names.
  for (const prefix of ["Can't record system audio (macOS ", "Can't cut item shorter than "]) {
    if (text.startsWith(prefix) && Object.hasOwn(dictionary, prefix)) {
      const suffix = text.slice(prefix.length);
      return dictionary[prefix] + (prefix.includes('(macOS ') ? suffix.replace(/\)$/, '）') : suffix);
    }
  }
  // Countdown options are generated from a number, not dictionary entries.
  if (/^\d+(?:\.\d+)?s$/.test(trimmed)) return text.replace(trimmed, trimmed.slice(0, -1) + ' 秒');
  return text;
}

function translateItem(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return item;
  let result = item;
  function set(field, value) {
    if (value === item[field]) return;
    if (result === item) result = {...item};
    result[field] = value;
  }
  const hasIdentity = item.preserveText === true || identityFields.some(key => Boolean(item[key]));
  if (!hasIdentity) {
    for (const field of displayFields) {
      if (Object.hasOwn(item, field)) set(field, translateDisplay(item[field]));
    }
  }
  // Only known presentation collections are visited. No recursion through
  // callbacks, action input, settings values, project data or file paths.
  for (const field of collectionFields) {
    if (Array.isArray(item[field])) set(field, translateNativeMenuItems(item[field]));
  }
  if (item.alternate && typeof item.alternate === 'object') set('alternate', translateItem(item.alternate));
  return result;
}

export function translateNativeMenuItems(items) {
  if (!Array.isArray(items)) return items;
  const translated = items.map(translateItem);
  return translated.some((item, index) => item !== items[index]) ? translated : items;
}

export function translateNativeTooltip(tooltip) {
  if (!tooltip || typeof tooltip !== 'object' || tooltip.preserveText === true) return tooltip;
  if (identityFields.some(key => Boolean(tooltip[key]))) return tooltip;
  const label = translateDisplay(tooltip.label);
  return label === tooltip.label ? tooltip : {...tooltip, label};
}
