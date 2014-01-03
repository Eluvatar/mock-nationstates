import string,codecs

__id_str__trans=string.maketrans(" ","_")
def id_str(name):
  i,i2=codecs.getencoder('ascii')(string.lower(name))
  id=i.translate(__id_str__trans)
  return id
