const fs = require('node:fs');
const { Resvg } = require('@resvg/resvg-js');
const [input, output, font] = process.argv.slice(2);
const svg = new Resvg(fs.readFileSync(input), {
  font: { fontFiles: [font], loadSystemFonts: false, defaultFontFamily: 'Arial' },
});
fs.writeFileSync(output, svg.render().asPng());
