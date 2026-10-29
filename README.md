# CyL-Laica

Proyecto de vigilancia del laicismo en Castilla y León a través de la prensa local asistido por IA.

El principal objetivo es realizar barridos estandarizados mediante IA de la prensa local y regional indexada para conocer la realidad del laicismo en Castilla y León.

Para ello se dispone de un prompt refinado con las instrucciones para que cualquier IA pueda realizar la tarea de búsqueda forma satisfactoria y consistente. La IA busca en una provincia cualquier reporte de prensa y los organiza en 4 ejes:

1) Autoridades democráticas en eventos confesionales.
2) Subvenciones y ayudas públicas dirigidas a la mejora y conservación del Patrimonio privado confesional e inmatriculado.
3) Subvenciones y ayudas públicas dirigidas a entidades de carácter confesional para otros servicios diferentes al Patrimonio (educación, sanidad, social...).
4) Declaraciones y noticias que muestran sucesos, posicionamientos o injerencias confesionales en el ámbito político y social.

En el reporte se discriminan noticias irrelvantes, se evitan duplicados, se selecciona la noticia con mayor información de las varias que haya disponibles para su seguimiento y se adjuntan los enlaces para consulta manual. Se señala la administración que otorga el dinero y la personalidad jurídica que lo recibe, fechas, así como los indicios sobre en qué boletín Autonómico, provincial o local debería o podría aparecer dicha concesión para verificación manual.


El segundo objetivo es organizar esta información de una manera visualmente atractiva e interactiva que permita comprender de forma sencilla la situación del laicismo en cuanto a cifras, permitiendo detectar las principales llaves que regulan los flujos económicos públicos hacia cauces confesionales, las administraciones titulares de esas llaves, y fechas en las que se activan, finalizan o renuevan. De forma que permita un planteamiento estratégico de los objetivos locales en cada provincia y en la totalidad de la autonomía.

Para logra esto se codifican los reportes en un archivo html que permite que cualquier usuario pueda consultarlo en sus dispositivos digitales con un navegador. Para la codificación se utiliza de nuevo la IA, mediante un prompt de instrucciones que le aporta consistencia en la tarea. Una vez codificados los datos se agregan al html de forma manual en la sección correspondiente.


