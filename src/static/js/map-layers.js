(function () {
    var ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';

    function esriLayer(service, attribution) {
        return L.tileLayer(ESRI + service + '/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 20,
            maxNativeZoom: 18,
            attribution: attribution || '© Esri'
        });
    }

    window.AqMap = {
        addBaseLayers: function (map) {
            var topo = esriLayer('World_Topo_Map', '© Esri, USGS, NOAA');
            var imagery = esriLayer('World_Imagery', '© Esri, Maxar, Earthstar Geographics');
            var street = esriLayer('World_Street_Map');
            var terrain = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                maxZoom: 20,
                maxNativeZoom: 17,
                subdomains: 'abc',
                attribution: '© OpenTopoMap, © OpenStreetMap'
            });
            var labels = esriLayer('Reference/World_Boundaries_and_Places');

            topo.addTo(map);
            L.control.layers(
                {
                    'نقشه توپوگرافی': topo,
                    'ماهواره': imagery,
                    'نقشه خیابانی': street,
                    'پستی و بلندی (منحنی تراز)': terrain
                },
                {'نام شهرها و مناطق': labels}
            ).addTo(map);

            map.on('baselayerchange', function (e) {
                if (e.layer === imagery && !map.hasLayer(labels)) {
                    labels.addTo(map);
                }
            });

            return {topo: topo, imagery: imagery, street: street, terrain: terrain, labels: labels};
        }
    };
})();
