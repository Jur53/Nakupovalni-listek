
INSERT INTO izdelki (ime, kategorija, enota) VALUES
('Mleko Pomurske mlekarne 1,5%', 'mlečni izdelki', '1L'),
('Mleko Pomurske mlekarne 3,5%', 'mlečni izdelki', '1L'),
('Mleko Alpsko 1,5%', 'mlečni izdelki', '1L'),
('Mleko Alpsko 3,5%', 'mlečni izdelki', '1L'),
('Kruh Drožnik Žito', 'pekovski izdelki', '400g');


INSERT INTO cene (izdelek_id, trgovina_id, cena) VALUES
(1, 1, 1.49), --mleko Pomurske mlekarne 1,5% pri Sparu
(1, 2, 1.49), --mleko Pomurske mlekarne 1,5% pri Mercatorju
(2, 1, 1.59), --mleko pomurske mlekarne 3,5% pri Sparu
(2, 2, 1.59), --mleko pomurske mlekarne 3,5% pri Mercatorju
(3, 1, 1.65),--mleko Alpsko 1,5% pri Sparu
(3, 2, 1.65), --mleko Alpsko 1,5% pri Mercatorju
(4, 1, 1.69), --mleko Alpsko 3,5% pri Sparu
(4, 2, 1.69), --mleko Alpsko 3,5% pri Mercatorju
(5, 1, 1.40), --kruh Drožnik Žito pri Sparu
(5, 2, 1.79); --kruh Drožnik Žito pri Mercatorju