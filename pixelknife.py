#!/usr/bin/python

"""Simple photo review to cut photos out and tag some for later operations.

Usage:

    Symlink pixel_knife.html as index.html into a directory with photos you want to review.
    Symlink includes directory as well as 'data'.

    ln -s `pwd`/pixel_knife.html $PHOTOS/index.html
    ln -s `pwd`/includes $PHOTOS/data

    PK=`pwd`/pixel_knife.py
    cd $PHOTOS
    python $PK

    Now open a web browser and browse to:

    http://localhost:9000

Requrirements:
    pyexiv2
    yaml

Ideas moving forward:
 - click for full resolution image, but put in a frame for good size
 - click to rotate image, or set degrees of rotation
 - pull metadata parsing code out of www module, make canonical var set
 - pull listing code out of www module, add filters for general use
 - icons on js side for exif data
 - fix exif data dup problem, make tests and pick vars
 - more complicated ratings for dealing with rev's and operating on say raw
 - side by side photo comparison in frames?
"""

import cgi
import copy
import datetime
import fractions
import glob
import json
import optparse
import os
import pyexiv2
import re
import sys
import time
import urlparse
import yaml
from BaseHTTPServer import HTTPServer
from SimpleHTTPServer import SimpleHTTPRequestHandler

DEFAULT_PORT = 9000

DEFAULT_TAGS = ('Rotate90-RIGHT',
                'Rotate90-LEFT',
                'TZ-Fix-Needed',
                'HDR_Set',)

PREVIEW_IMAGE_TYPES = ('jpg', 'JPG', 'png')

# Selection of Exif tags, more useful for Nikon, need
# Canon, etc. TZ tags for time correction operations
EXIF_KEYS = [
  'Exif.Image.Artist', # string me
  'Exif.Image.DateTime', # datetime.datetime
  'Exif.Image.DateTimeOriginal', # datetime.datetime
  'Exif.Image.Make', # camera make
  'Exif.Image.Model', # camera model
  'Exif.Image.Orientation', # small int lookup
  'Exif.Image.ProcessingSoftware', # string ufraw
  'Exif.Photo.DateTimeOriginal', # datetime.datetime
  'Exif.Photo.DateTimeDigitized', # datetime.datetime
  'Exif.Photo.ExposureBiasValue', # int?
  'Exif.Photo.ExposureTime', # fraction
  'Exif.Photo.FocalLength', # faction
  'Exif.Photo.FocalLengthIn35mmFilm', # fraction
  'Exif.Photo.Flash', # bool?
  'Exif.Photo.FNumber', # fraction
  'Exif.Photo.ISOSpeedRatings', # int
  'Exif.Photo.MeteringMode', # need to look up mode, small int
  'Exif.Photo.WhiteBalance', # need to look up small int
  'Exif.Nikon3.FlashSetting', # str
  'Exif.Nikon3.FlashDevice', # str, empty w/ on board?
  'Exif.Nikon3.Focus', # str
  'Exif.Nikon3.ISOSpeed', # int tuple
  'Exif.Nikon3.Quality', # str
  'Exif.Nikon3.WhiteBalance', # str
  'Exif.NikonWt.DaylightSavings', # small int, bool?
  'Exif.NikonWt.Timezone', # in minutes? -480?
]


def GetImageListing(extensions=PREVIEW_IMAGE_TYPES):
  """Look in the current directory and grab image filenames.

  TODO: pre-scan exif and send resolution which each photo,
  also possibly jpeg orientation
  """
  image_paths = []
  for ext in extensions:
    image_paths.extend(glob.glob('*.%s' % (ext)))
    image_paths.sort()
  return {'images': image_paths}


def GetImageMetadata(image_path):
  """Given an image file path grab and return metadata."""
  metadata = {}
  metadata['path'] = image_path
  meta = pyexiv2.ImageMetadata(image_path)
  meta.read()
  for k in EXIF_KEYS:
    try:
      val = meta[k].value
    except KeyError:
      continue
    if isinstance(val, datetime.datetime):
      metadata[k] = val.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(val, fractions.Fraction):
      metadata[k] = '%d / %d' % (val.numerator, val.denominator)
    elif isinstance(val, str):
      metadata[k] = val.strip()
    else:
      metadata[k] = val
  return metadata


class BorgKeyValStore(object):
  """Alex Martelli's Borg pattern, one state, many instances.

  Adds basic backup functionality for resuming a review session
  with all of your scores and tags.
  """
  _kvStore = {}

  def __init__(self):
    self.store = self._kvStore

  def backup(self, output_filename):
    print 'Doing Borgstore backup to " %s".' % output_filename
    print 'Discarding EXIF data for now'
    backup_store = copy.copy(self.store)
    # different objects in exif classes don't serialize well, drop exif data
    backup_store.pop('image_data', '')

    if os.path.exists(output_filename):
      if not UserPromptOK('File exists. Overwrite? (y/n) '):
        output_filename = UserPromptFilename('New filename to backup to '
                                             '[%default%]: ',
                                             default=output_filename)
    try:
      with open(output_filename, 'w') as f:
        yaml.dump(backup_store, f)
    except IOError as e:
      print 'Failed to write backup file!\n%s' % e   
      raise
    print 'Backed up BorgStore to %s' % output_filename

  def restore(self, input_filename):
    print 'Doing restoration from backup file "%s".' % input_filename
    try:
      with open(input_filename, 'r') as f:
        data = yaml.safe_load(f.read())
        # Update the class pointer and instance pointer together.
        BorgKeyValStore._kvStore = data
        self.store = self._kvStore
    except IOError:
      print 'Error opening restore file %s' % input_filename
      raise
    except:
      print 'Take note of exception here... what kind again?'
      raise


class ImageReviewStore(BorgKeyValStore):

  def __init__(self):
    super(ImageReviewStore, self).__init__()
    print 'running image review store init'

    self.store.setdefault('image_data', {})
    self.store.setdefault('image_ratings', {})
    self.store.setdefault('image_tags', {})
    self.store.setdefault('tags_to_images', {})
    self.store.setdefault('tags_registered', set())
    self.store.setdefault('ms_registered_tag_map', {})
    # self.store['tags_registered'].update(DEFAULT_TAGS)
    self._CheckAndRegisterTags(DEFAULT_TAGS)


  def GetAllImagePaths(self):
    ### Add a real populate method
    return GetImageListing()

  def GetImageInfo(self, image_path):
    """Get Exif metadata about image_path, cache and return it."""
    metadata_store = self.store['image_data']
    metadata = metadata_store.get(image_path)
    if not metadata:
      metadata = GetImageMetadata(image_path)
      metadata_store[image_path] = metadata
    return metadata

  def GetImageRating(self, image_path):
    rating_store = self.store['image_ratings']
    rated = rating_store.setdefault(image_path, 0)
    return rated

  def GetAllImageRatings(self):
    return self.store['image_ratings']

  def _ChangeImageRating(self, image_path, value):
    ## print 'changing image rating %s plus %s' % (image_path, value)
    rating_store = self.store['image_ratings']
    rated = rating_store.setdefault(image_path, 0)
    rating_store[image_path] = rated + value
    return {image_path: rating_store[image_path]}

  def IncrementImageRating(self, image_path):
    return self._ChangeImageRating(image_path, 1)

  def DecrementImageRating(self, image_path):
    return self._ChangeImageRating(image_path, -1)

  def GetAllImageTags(self):
    tag_maps = {}
    tag_maps['image_tags'] = self.store['image_tags']
    tag_maps['tags_to_images'] = self.store['tags_to_images']
    return tag_maps

  def ChangeImageTags(self, image_path, tags):
    tags_to_images = self.store['tags_to_images']
    all_image_tags = self.store['image_tags']

    current_tags = set(all_image_tags.get(image_path, []))
    checked_tags = self._CheckAndRegisterTags(tags)

    # keep the tags-to-images map up to date
    to_unlink = current_tags.difference(checked_tags)
    to_link = set(checked_tags).difference(current_tags)
    for t in to_unlink:
      tagged_list = tags_to_images.get(t)
      if tagged_list:
        tagged_list.remove(image_path)
    for t in to_link:
      tagged_list = tags_to_images.get(t)
      if tagged_list:
        tagged_list.append(image_path)

    # trust clients tags, add sanity someday...
    #TODO not ok, fix
    all_image_tags[image_path] = tags
    return {image_path: all_image_tags[image_path]} 

  def GetImageTags(self, image_path):
    tag_store = self.store['image_tags']
    return tag_store.get(image_path, [])

  def _CheckAndRegisterTags(self, tags):
    tagreg_store = self.store['tags_registered']
    # print 'tagreg before: %s' % list(tagreg_store)
    # could stand to add some sanity to tags
    
    #current_ids = [ms_id for ms_id, _ in self.store['ms_registered_tag_map'].values()]
    current_ids = self.store['ms_registered_tag_map'].values()
    if current_ids:
      next_usable_id = max(current_ids) + 1
    else:
      next_usable_id = 0
    # Need to keep run-persistent tag ids
    new_tags = set(tags).difference(tagreg_store)
    if new_tags:
      for idx, tag in enumerate(new_tags, next_usable_id):
        # self.store['ms_registered_tag_map'][tag] = (idx, tag)
        self.store['ms_registered_tag_map'][tag] = idx

      self.store['tags_registered'].update(new_tags)
    # print 'tagreg after: %s' % list(tagreg_store)
    return tags

  # def GetRegisteredTags(self):
  #   return list(self.store['tags_registered'])

  def GetMagicSuggestTags(self):
    return [dict(id=idx, name=tag)
            for tag, idx in self.store['ms_registered_tag_map'].items()]
            #for idx, tag in self.store['ms_registered_tag_map'].values()]

  def GetMagicSuggestImageTags(self, image_path):
    # ids = []
    # for tag in self.GetImageTags(image_path):
    #   idx, _ = self.store['ms_registered_tag_map'][tag]
    #   ids.append(idx)
    tag_map = self.store['ms_registered_tag_map']
    ids = [tag_map[tag] for tag in self.GetImageTags(image_path)]
    return ids


class Handler(SimpleHTTPRequestHandler):
  """Overrides basic handler and router for SimpleHTTPServer.

  Routes requests and passes queries dictionaries to handler
  methods.  Which in turn query the review store and return
  JSON serialized results to the javascript frontend.
  """

  def getQueryDict(self):
    """Returns GET or POST form data in it a uniform way."""
    query_data = {}
    if self.requestline.startswith('GET'):
      url = urlparse.urlparse(self.path)
      query_data = urlparse.parse_qs(url.query)
    elif self.requestline.startswith('POST'):
      ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
      if ctype == 'application/x-www-form-urlencoded':
        length = int(self.headers.getheader('content-length'))
        query_data = cgi.parse_qs(self.rfile.read(length), keep_blank_values=1)
    print 'getQueryDict: %s' % query_data
    return query_data

  def sendJsonResponse(self, data, errors=''):
    """Send appropriate headers and return code and flush JSON."""
    mimetype = 'application/json'
    json_data = EncodeJsonResponse(data, errors)
    self.send_response(200)
    self.send_header('Content-type', mimetype)
    self.end_headers()
    self.wfile.write(json_data)

  def handleFileInfoQuery(self):
    """Handle request for single images Exif metadata."""
    metadata = {}
    errors = ''
    query_data = self.getQueryDict()
    store = ImageReviewStore()
    if query_data.get('file'):
      # TODO put in a fix here this explodes with no files
      metadata = store.GetImageInfo(query_data.get('file')[0]) 
    else:
      errors = 'No image path provided.'
    self.sendJsonResponse(metadata, errors)

  def handleRateFilePost(self):
    """Handle incrementing or decrementing an images rating.

    Specific values provided by the user are ignored, only whether
    it is positive or negative are checked, and the rating it changed
    by one.  Voting can occur by the same user as many times as they
    want -- just keep clicking.
    """
    results = {}
    errors = []
    query_data = self.getQueryDict()
    image_file = query_data.get('file')
    try:
      value = int(query_data.get('vote')[0])
    except (ValueError, IndexError):
      errors.append('Vote is not an integer value.')
    if not image_file:
      errors.append('No image path provided.')
    if not errors:
      # get a pointer to the review store
      store = ImageReviewStore()
      image = image_file[0]
      # maybe send a nasty-gram if value == 0 or drop
      if value > 0:
        results = store.IncrementImageRating(image)
      else:
        results = store.DecrementImageRating(image)
    self.sendJsonResponse(results, errors)

  def handleTagFilePost(self):
    """Handle a request to change an images tags."""
    results = {}
    errors = []
    store = ImageReviewStore()
    query_data = self.getQueryDict()
    image_file = query_data.get('image_path')
    #TODO handle user provided data, filter, escape, chop
    try:
      tags = [str(t) for t in query_data.get('tags', [])]
    except ValueError:
      errors.append('Tags malformed or not provided.')
    if not image_file:
      errors.append('No image path provided.')
    if not errors:
      image = image_file[0]
      print 'handleTagFilePost: %s gets tags: %s' % (image, tags)
      store.ChangeImageTags(image, tags)
      results = store.GetImageTags(image)
    else:
      print 'handleTagFilePost errors: %s' % ('\n'.join(errors))
    self.sendJsonResponse(results, errors) 

  def handleAllFileTagsQuery(self):
    """Handle request for all tags."""
    errors = []
    store = ImageReviewStore()
    query_data = self.getQueryDict()
    results = store.GetAllImageTags()
    self.sendJsonResponse(results, errors)

  def handleTagsQuery(self):
    """Handle request to read a single images tags."""
    results = {}
    errors = []
    store = ImageReviewStore()
    query_data = self.getQueryDict()
    try:
      image_path = query_data.get('file')[0]
    except (KeyError, IndexError):
      errors.append('Bad file selection for tag query.')
    else:
      ms_tags = store.GetMagicSuggestTags()
      ms_vals = store.GetMagicSuggestImageTags(image_path)
      results = dict(tags=ms_tags, values=ms_vals)
    self.sendJsonResponse(results, errors)

  def handleFileRatingQuery(self):
    """Handle query for single images rating data.

    Should be expanded to return all rating data
    and the frontend can cache it -- reduing roundtrips
    significantly.
    """
    results = {}
    errors = []
    query_data = self.getQueryDict()
    image_file = query_data.get('file')
    store = ImageReviewStore()
    if image_file:
      # fix horrid hack here for first element
      results = {image_file[0]: store.GetImageRating(image_file[0])}
    else:
      results = store.GetAllImageRatings()
    self.sendJsonResponse(results, errors)

  def do_GET(self):
    """Router for my SimpleHTTPServer."""
    store = ImageReviewStore()
    if self.path == '/allz':
      images = store.GetAllImagePaths()
      self.sendJsonResponse(images)
    elif self.path.startswith('/infoz'):
      self.handleFileInfoQuery()
    elif self.path.startswith('/votez'):
      self.handleFileRatingQuery()
    elif self.path.startswith('/tagz'):
      self.handleTagsQuery()
    elif self.path.startswith('/imgtagz'):
      self.handleAllFileTagsQuery()
    else:
      SimpleHTTPRequestHandler.do_GET(self)

  def do_POST(self):
    """Router for my SimpleHTTPServer."""
    if self.path.startswith('/votez'):
      self.handleRateFilePost()
    elif self.path.startswith('/tagz'):
      self.handleTagFilePost()

 
def EncodeJsonResponse(payload, errors=''):
  """Wrap data and errors in simple schema and return as JSON."""
  data = {'data': payload, 'errors': errors}
  return json.JSONEncoder().encode(data)


def UserPromptOK(prompt, affirmative_regex='[yY]'):
  user_oks = False
  if re.search(affirmative_regex, raw_input(prompt)):
    user_oks = True
  return user_oks


def UserPromptFilename(prompt, default='', test_perms='w'):
  """Prompt the user for a filename to use"""
  f = None
  fname = ''
  if '%default%' in prompt:
    prompt = re.sub('%default%', default, prompt)
  while not fname:
    fname = raw_input(prompt) or default
    try:
      with open(fname, test_perms) as f:
        pass
    except IOError as e:
      print 'Not a usable filename.'
      print '%s' % e
      fname = ''
  return fname
    

def main(args, options):
  store = ImageReviewStore()
  if options.restore:
    store.restore(options.restore)
  try:
    print 'Starting HTTP server on port %s.' % DEFAULT_PORT
    server = HTTPServer(('', DEFAULT_PORT), Handler)
    server.serve_forever()
  except KeyboardInterrupt:
    store.backup(options.outfile)
    print 'Shutting down HTTP server.'
    server.socket.close()


if __name__ == '__main__':

  parser = optparse.OptionParser()

  # parser.add_option("-t", "--time", action="store_true", dest="timeon",
  #                   default=False, help="Show Exif time stamps")
  parser.add_option("-r", "--restore", dest="restore",
                    help="Restore state from a yaml backup file.")
  parser.add_option("-o", "--outfile", dest="outfile",
                    help="Specify path to write yaml backup file.")

  parser.set_defaults(outfile='borgstore.yaml')
  options, args = parser.parse_args()

  main(args, options)
