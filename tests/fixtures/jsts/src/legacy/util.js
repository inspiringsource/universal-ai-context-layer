const path = require('path');

function slugify(text) {
  return text.toLowerCase().replace(/\s+/g, '-');
}

exports.joinSlug = function (base, text) {
  return path.join(base, slugify(text));
};

module.exports.slugify = slugify;
