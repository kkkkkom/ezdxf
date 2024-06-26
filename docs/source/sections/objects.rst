Objects Section
===============

.. module:: ezdxf.sections.objects

The OBJECTS section is the home of all none graphical objects of a DXF document.
The OBJECTS section is accessible by the :attr:`Drawing.objects` attribute.


Convenience methods of the :class:`~ezdxf.document.Drawing` object to create essential
structures in the OBJECTS section:

    - IMAGEDEF: :meth:`~ezdxf.document.Drawing.add_image_def`
    - UNDERLAYDEF: :meth:`~ezdxf.document.Drawing.add_underlay_def`
    - RASTERVARIABLES: :meth:`~ezdxf.document.Drawing.set_raster_variables`
    - WIPEOUTVARIABLES: :meth:`~ezdxf.document.Drawing.set_wipeout_variables`

.. seealso::

    DXF Internals: :ref:`objects_section_internals`

.. class:: ObjectsSection

    .. autoattribute:: rootdict

    .. automethod:: __len__

    .. automethod:: __iter__

    .. automethod:: __getitem__

    .. automethod:: __contains__

    .. automethod:: query

    .. automethod:: add_dictionary

    .. automethod:: add_dictionary_with_default

    .. automethod:: add_dictionary_var

    .. automethod:: add_geodata

    .. automethod:: add_image_def

    .. automethod:: add_placeholder

    .. automethod:: add_underlay_def

    .. automethod:: add_xrecord

    .. automethod:: set_raster_variables

    .. automethod:: set_wipeout_variables




