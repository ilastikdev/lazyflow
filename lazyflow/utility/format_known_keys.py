###############################################################################
#   lazyflow: data flow based lazy parallel computation framework
#
#       Copyright (C) 2011-2014, the ilastik developers
#                                <team@ilastik.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the Lesser GNU General Public License
# as published by the Free Software Foundation; either version 2.1
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# See the files LICENSE.lgpl2 and LICENSE.lgpl3 for full text of the
# GNU Lesser General Public License version 2.1 and 3 respectively.
# This information is also available on the ilastik web site at:
#		   http://ilastik.org/license/
###############################################################################
import string

def format_known_keys(s, entries):
    """
    Like str.format(), but 
     (1) accepts only a dict and 
     (2) allows the dict to be incomplete, 
         in which case those entries are left alone.
    
    Examples:
    
    >>> format_known_keys("Hello, {first_name}, my name is {my_name}", {'first_name' : 'Jim', 'my_name' : "Jon"})
    'Hello, Jim, my name is Jon'
    
    >>> format_known_keys("Hello, {first_name:}, my name is {my_name}!", {"first_name" : [1,2,2]})
    'Hello, [1, 2, 2], my name is {my_name}!'
    """
    fmt = string.Formatter()
    it = fmt.parse(s)
    s = ''
    for i in it:
        if i[1] in entries:
            val = entries[ i[1] ]
            s += i[0] + fmt.format_field( val, i[2] )
        else:
            # Replicate the original stub
            s += i[0]
            if i[1] or i[2]:
                s += '{'
            if i[1]:
                s += i[1]
            if i[2]:
                s += ':' + i[2]
            if i[1] or i[2]:
                s += '}'
    return s

if __name__ == "__main__":
    import doctest
    doctest.testmod()
