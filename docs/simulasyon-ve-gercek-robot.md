# Simülasyon ↔ Gerçek Robot — Kullanım ve Entegrasyon

Bu belge iki şeyi anlatır: Gazebo simülasyonunun nasıl kullanıldığı ve orada
geliştirilen haritalama/navigasyon yığınının gerçek ASTRO'ya nasıl taşınacağı.

Tüm parametreler ve topic adları kaynak koddan doğrulanmıştır; "muhtemelen
böyledir" diye yazılmış hiçbir şey yok. Henüz var olmayan parçalar açıkça
**eksik** olarak işaretlenmiştir.

---

## 1. Tasarım: ne ortak, ne farklı

Tek bir gövde tanımı (`astro_description/urdf/astro.urdf.xacro`) her iki dünyada
da kullanılır. Simülasyona özgü her şey ayrı bir dosyadadır ve yalnızca
`sim_mode:=true` iken dahil edilir:

```
astro.urdf.xacro          ← ortak: linkler, eklemler, ölçüler, atalet
  └─ astro_gazebo.xacro   ← YALNIZCA sim_mode:=true: eklentiler, sensörler, sürtünme
```

Bu ayrım kasıtlı: gerçek robotta `sim_mode` varsayılan olarak `false`'tur, yani
Gazebo eklentileri hiç yüklenmez ve tf ağacı simülasyondan etkilenmez.
Doğrulama:

```bash
xacro ros2_ws/src/astro_description/urdf/astro.urdf.xacro sim_mode:=false | grep -c "<gazebo"
# 0  olmalı
```

Sensör topic adları **bilerek aynı** tutulmuştur, böylece algı düğümleri iki
dünyada da değişmeden çalışır:

| Topic | Simülasyonda kaynak | Gerçek robotta kaynak |
|---|---|---|
| `/scan` | `gpu_lidar` sensörü (astro_gazebo.xacro) | `rplidar_node` (astro_lidar) |
| `/scan_filtered` | — (sim taraması zaten temiz) | `scan_filter_node` |
| `/imu` | `imu` sensörü | — (gerçekte `/imu/data_raw`, **ad farklı**) |
| `/oak/rgb/image_raw` | `camera` sensörü | `oak_spatial_native_node` |
| `/joint_states` | `JointStatePublisher` eklentisi | `serial_bridge` (enkoder tick'lerinden) |
| `/odom` | `DiffDrive` eklentisi | **YOK — bkz. §4** |
| `odom → base_footprint` tf | `DiffDrive` eklentisi | **YOK — bkz. §4** |
| Hareket komutu | `/cmd_vel` (`geometry_msgs/Twist`) | `/wheel_cmds` (`astro_base/WheelCmd`) — **arayüz farklı** |
| Kafa komutu | `/head_yaw_cmd` (`std_msgs/Float64`, radyan) | `/head_cmd` (`astro_base/HeadCmd`, **derece**) |

---

## 2. Simülasyon kullanımı

### Ön koşullar

```bash
sudo apt install -y ros-humble-slam-toolbox ros-humble-nav2-bringup \
  ros-humble-nav2-common ros-humble-robot-localization \
  ros-humble-joint-state-publisher ros-humble-twist-mux
```

Simülatör **Gazebo Harmonic**'tir (`gz sim`, apt paketi `ros-humble-ros-gzharmonic`).
Gazebo Classic (`libgazebo_ros_*.so`) ve Ignition Fortress (`ignition-gazebo6-*`)
farklı eklenti dosya adları kullanır; bu robot onlarda **sessizce** yüklenmez —
düğümler açılır ama sensör verisi hiç gelmez.

Her terminalde:

```bash
cd ~/Documents/Projeler/barline/astr1
source .venv/bin/activate
source ros2_ws/install/setup.bash      # zsh: setup.zsh
```

### Aşama 1 — dünya

```bash
ros2 launch astro_sim simulation.launch.py
```

İki pencere açılır. **Gazebo Sim** fiziksel gerçeği gösterir (koridor, üç oda,
0.9 m kapılar, mobilya; robot koridorda `(-4, 0)`'da doğar). **RViz2** robotun
kendi algısını gösterir — ikisi arasındaki fark SLAM'in kapatmaya çalıştığı
boşluktur.

| Argüman | Varsayılan | Ne yapar |
|---|---|---|
| `world` | `astro_indoor.sdf` | `astro_sim/worlds` altındaki dünya |
| `rviz` | `true` | RViz2'yi de başlat |
| `headless` | `false` | `gz sim -s` — pencere yok, sunucu var |
| `x` / `y` / `z` / `yaw` | `-4.0` / `0.0` / `0.10` / `0.0` | Doğma konumu |

Sürmek için:

```bash
ros2 run teleop_twist_keyboard teleop_twist_keyboard
```

`i` ileri · `,` geri · `j`/`l` dön · `k` dur. Tuşların gitmesi için **bu pencere
odakta olmalı**.

### Aşama 2 — haritalama

```bash
ros2 launch astro_navigation slam.launch.py
```

Robotu her odaya sokun ve **başladığınız yere geri dönün** — döngü kapandığında
birikmiş hata bir anda düzelir. Sonra kaydedin:

```bash
ros2 run nav2_map_server map_saver_cli \
  -f ros2_ws/src/astro_navigation/maps/astro_indoor --ros-args -p use_sim_time:=true
```

### Aşama 3 — navigasyon

```bash
ros2 launch astro_navigation navigation.launch.py
```

RViz'de **Nav2 Goal** ile hedef verin, ya da komut satırından:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 6.0, y: 0.0}}}}"
```

`map` çerçevesinin orijini doğma noktasıdır. Bu dünyada
`map(x, y) = dünya(x − 4, y)`.

---

## 3. Gerçek robot — bugün çalışan kısım

### udev kuralları (bir kez)

Seri portların her açılışta aynı adı alması için:

```bash
sudo cp ros2_ws/src/astro_bringup/config/udev/99-astro-sensors.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Bu kurallar şu sembolik bağları oluşturur:

| Cihaz | USB VID:PID | Sembolik bağ |
|---|---|---|
| Arduino Mega (orijinal) | `2341:0042` | `/dev/astro_arduino` |
| Arduino Mega (CH340 klon) | `1a86:7523` | `/dev/astro_arduino` |
| RPLIDAR A1 (CP210x) | `10c4:ea60` | `/dev/astro_lidar` |
| ReSpeaker Mic Array | `2886:0018` | (yalnızca izinler) |

Kontrol: `ls -l /dev/astro_*`

### Çalıştırma

```bash
ros2 launch astro_bringup robot.launch.py     # taban + lidar + kamera + ses + AI
ros2 launch astro_lidar lidar.launch.py       # yalnızca LiDAR
```

`lidar.launch.py` portu bulamazsa düğümü **atlar** ve uyarı basar; RPLIDAR takılı
değilken bu beklenen davranıştır, hata değil. Port bulunamazsa sırayla
`/dev/ttyUSB1`, `/dev/ttyUSB0`, `/dev/ttyACM1`, `/dev/ttyACM0` ve
`/dev/astro_*` denenir.

### Gerçek robotta bugün ne var

- ✅ Enkoderler: Arduino quadrature tick sayar, `serial_bridge` bunları
  tekerlek açısına çevirip `/joint_states` yayınlar
- ✅ IMU: `/imu/data_raw`
- ✅ LiDAR: `/scan` ve filtrelenmiş `/scan_filtered`
- ✅ Kamera: `/oak/rgb/image_raw`
- ✅ tf: `base_footprint → base_link → …` (robot_state_publisher, URDF'ten)
- ❌ **Odometri yok**
- ❌ **`/cmd_vel` arayüzü yok**

---

## 4. ⚠️ Entegrasyon boşluğu — SLAM/Nav2 için eksik olan

Bu, gerçek robota geçişteki **tek gerçek engeldir** ve bilinçli olarak açıkça
yazılmıştır.

`serial_bridge.py` şunları yayınlar: `/imu/data_raw`, `/joint_states`,
`/arduino/diagnostics`. Şunlara abonedir: `/wheel_cmds` (`WheelCmd`:
`left_rpm`, `right_rpm`) ve `/head_cmd` (`HeadCmd`: `angle_deg`).

**`/odom` yayınlamaz ve `odom → base_footprint` tf'i göndermez.**

Bunun sonucu:

| Bileşen | Neden çalışmaz |
|---|---|
| `slam_toolbox` | `odom_frame` zorunlu; tf zinciri `map → odom → base_footprint` kurulamaz |
| `nav2` AMCL | Aynı sebep |
| `nav2` controller | `/cmd_vel` yayınlar, ama kimse dinlemiyor — taban `/wheel_cmds` bekliyor |
| `nav2` costmap | `odom` global çerçevesi yok |

### Eksik parça: bir `base_bridge` düğümü

Yazılması gereken ~150 satırlık düğüm iki yönü de kapatır:

**a) Odometri (ileri kinematik).** `/joint_states`'ten tekerlek açılarını alır:

```
Δs_sol  = Δθ_sol  × wheel_radius
Δs_sağ  = Δθ_sağ  × wheel_radius
Δs      = (Δs_sağ + Δs_sol) / 2
Δφ      = (Δs_sağ − Δs_sol) / wheel_separation
x += Δs·cos(φ + Δφ/2) ,  y += Δs·sin(φ + Δφ/2) ,  φ += Δφ
```

`nav_msgs/Odometry` olarak `/odom`'a yayınlar ve `odom → base_footprint`
tf'ini gönderir.

**b) Hız komutu (ters kinematik).** `/cmd_vel`'den `geometry_msgs/Twist` alır:

```
v_sol = v − ω·wheel_separation/2      rpm_sol = v_sol / wheel_radius × 60 / 2π
v_sağ = v + ω·wheel_separation/2      rpm_sağ = v_sağ / wheel_radius × 60 / 2π
```

`astro_base/WheelCmd` olarak `/wheel_cmds`'e yayınlar.

Gereken sabitler URDF'te zaten var: `wheel_radius = 0.06`,
`wheel_separation = 0.26`.

> **Alternatif:** `ros2_control` + `diff_drive_controller` aynı işi standart
> şekilde yapar, ama Arduino için bir donanım arayüzü (`hardware_interface`)
> yazmayı gerektirir — mevcut seri protokolü sarmalayan küçük bir düğümden
> belirgin şekilde daha büyük bir iş.

### 🚨 Aynı anda tek odometri yayıncısı

Simülasyonda `odom → base_footprint` tf'ini DiffDrive eklentisi üretir. Gerçek
robotta bunu yeni `base_bridge` üretecek. **İkisi asla birlikte çalışmamalıdır**;
aynı dönüşüme iki yayıncı olursa tf kullanılamaz hâle gelir ve teşhisi zordur.
Bu yüzden `astro_gazebo.xacro` yalnızca `sim_mode:=true` ile yüklenir.

---

## 5. Parametreler

### 5.1 Fiziksel ölçüler — `astro.urdf.xacro`

Bunlar **gerçek robottan ölçülmeli**; simülasyon bu değerlere göre kurulur,
tersi değil.

| Parametre | Değer | Anlamı |
|---|---|---|
| `base_length` × `base_width` × `base_height` | 0.30 × 0.25 × 0.12 m | Gövde kutusu |
| `wheel_radius` | 0.06 m | Tahrik tekerleği yarıçapı |
| `wheel_width` | 0.04 m | Lastik genişliği |
| `wheel_y_offset` | 0.13 m | Merkezden tekerleğe |
| `wheel_separation` | 0.26 m | `2 × wheel_y_offset` — türetilir |
| `ground_clearance` | 0.03 m | Gövde altı boşluğu = denge tekeri yarıçapı |
| `caster_x_offset` | 0.11 m | Denge tekeri merkezden uzaklığı |
| `caster_trail` | 0.015 m | Döner tekerin takip mesafesi |
| `laser_joint` origin | `[0.10, 0, body_top+0.02]` | LiDAR'ın base_link'e göre yeri |

> **Geometri kuralı:** tekerlek merkezleri `base_footprint`'ten tam
> `wheel_radius` yükseklikte olmalıdır. Eski sürümde eklem `-base_height/2`
> konumundaydı ve tekerlekler zeminin 6 cm altında kalıyordu — RViz'de zemin
> düzlemi olmadığı için görünmüyordu, Gazebo'da robot yere gömülü doğuyordu.

### 5.2 `serial_bridge` — `astro_bringup/config/astro_params.yaml`

| Parametre | Varsayılan | Not |
|---|---|---|
| `port` | `/dev/astro_arduino` | udev sembolik bağı |
| `baud` | `500000` | Firmware ile aynı olmalı |
| `connect_retry_sec` | `2.0` | Arduino yokken yeniden deneme aralığı |
| `frame_id_imu` | `imu_link` | URDF'teki link adıyla aynı olmalı |
| `ticks_per_rev_left/right` | `2048.0` | **Kalibre edilmeli** — bkz. §6 |
| `wheel_radius_left/right` | `0.06` | URDF ile **aynı** olmalı |

### 5.3 LiDAR — `astro_lidar/config/lidar_params.yaml`

| Parametre | Varsayılan | Not |
|---|---|---|
| `serial_port` | `/dev/astro_lidar` | |
| `serial_baudrate` | `115200` | A1 için; A2/A3 farklıdır |
| `frame_id` | `laser_frame` | URDF'teki link adı |
| `scan_mode` | `Standard` | |
| `range_min` / `range_max` | `0.15` / `12.0` | Simülasyondaki `gpu_lidar` ile **aynı** |

### 5.4 SLAM — `astro_navigation/config/slam_toolbox.yaml`

| Parametre | Sim | Gerçek | Not |
|---|---|---|---|
| `use_sim_time` | `true` | **`false`** | Launch argümanından gelir |
| `scan_topic` | `/scan` | **`/scan_filtered`** | Gerçek LiDAR NaN üretir |
| `base_frame` | `base_footprint` | aynı | |
| `odom_frame` | `odom` | aynı | §4'teki düğüm bunu üretmeli |
| `max_laser_range` | `12.0` | aynı | RPLIDAR A1'in gerçek menzili |
| `resolution` | `0.05` | aynı | 0.9 m kapı = 18 hücre |
| `minimum_travel_distance` | `0.2` m | aynı | |

Gerçek robotta çağrı:

```bash
ros2 launch astro_navigation slam.launch.py \
  use_sim_time:=false scan_topic:=/scan_filtered
```

### 5.5 Nav2 — `astro_navigation/config/nav2_params.yaml`

| Parametre | Değer | Neden |
|---|---|---|
| `robot_radius` | `0.20` m | 0.30 × 0.25 gövdenin çevrel yarıçapı |
| `inflation_radius` | `0.35` m | Kapılar 0.9 m; büyütülürse geçiş kapanır ve planlayıcı yol bulamaz |
| `max_vel_x` | `0.35` m/s | |
| `max_vel_theta` | `0.8` rad/s | |
| `acc_lim_x` / `acc_lim_theta` | `1.0` / `2.0` | **Tabanın gerçekte uygulayabildiğiyle aynı olmalı** |
| `laser_max_range` (AMCL) | `12.0` | |
| `alpha1..alpha5` | `0.2/0.2/0.1/0.1/0.1` | Ölçülen odometri hatasından türetildi |
| `xy_goal_tolerance` | `0.20` m | |

> `acc_lim_*` değerleri simülasyonda DiffDrive eklentisinin sınırlarıyla
> eşleştirildi. Gerçek robotta motor sürücünüzün gerçek ivmesini ölçüp bu
> değerleri güncelleyin; controller uygulanamayan bir ivme isterse gerçek
> hareket komuttan sapar ve konum tahmini bozulur.

---

## 6. Kalibrasyon — simülasyondan gerçeğe

Simülasyonda kullandığım yöntem gerçek robotta da geçerlidir; tek fark
"gerçek konum"un Gazebo yerine şerit metreyle ölçülmesidir.

### 6.1 `ticks_per_rev` (en kritik)

Robotu yerden kaldırın, tek tekerleği elle **tam 10 tur** çevirin:

```bash
ros2 topic echo /joint_states --once     # önce
# 10 tur çevir
ros2 topic echo /joint_states --once     # sonra
```

`position` farkı `10 × 2π = 62.83` rad olmalı. Değilse:

```
ticks_per_rev_doğru = ticks_per_rev_mevcut × (ölçülen / 62.83)
```

### 6.2 Düz sürüş → `wheel_radius`

Yerde 2 m işaretleyin, robotu düz sürün, `/odom` deltasını gerçek mesafeyle
karşılaştırın:

```
wheel_radius_doğru = wheel_radius_mevcut × (gerçek / odom)
```

### 6.3 Yerinde dönüş → `wheel_separation`

Robotu tam 10 tur döndürün (`360° × 10`), `/odom` yaw toplamına bakın:

```
wheel_separation_doğru = wheel_separation_mevcut × (odom_açı / gerçek_açı)
```

Sırayla yapın: önce tick, sonra yarıçap, sonra tekerlek arası — her biri bir
sonrakini etkiler.

### 6.4 Beklenen hata düzeyi

Simülasyonda döner denge tekeri modeliyle ölçülen değerler, gerçek robot için
de makul bir hedeftir:

| Hareket | Odometri hatası |
|---|---|
| Düz sürüş | −2.7 % |
| Yay (0.25 m/s, 0.6 rad/s) | mesafe −0.8 %, açı +2.4° |
| Yerinde dönüş | +14° / 180° (≈ %8) |

Yerinde dönüşteki hata tahrik tekerleklerinin kaçınılmaz yanal sürtünmesinden
gelir ve gerçek robotta da vardır. SLAM'in düzeltmesi gereken şey tam olarak
budur: simülasyonda ~35 m'lik bir turda odometri 4.2 m ve 17° sapmışken, SLAM
pozu gerçekten yalnızca **5 mm ve 0.04°** uzaktı.

---

## 7. Sorun giderme

### `use_sim_time` uyuşmazlığı

Boru hattındaki **her** düğümde aynı olmalı. Bir düğüm duvar saatini
kullanırsa tf zaman damgaları tutmaz ve SLAM sessizce durur ya da
"lookup would require extrapolation into the future" verir.

```bash
ros2 param get /slam_toolbox use_sim_time
```

### "Detected jump back in time. Clearing TF buffer"

Neredeyse her zaman **artık süreçler** demektir. Önceki bir çalıştırmadan kalan
köprü/düğüm eski zaman damgalarıyla `/tf`'e yayın yapmaya devam eder; her
Gazebo yeniden başlatmasında simülasyon saati sıfırlandığı için tf zamanda geri
sıçrar ve SLAM tamponunu sürekli siler.

```bash
ros2 topic info /tf          # yayıncı sayısı beklenenden fazlaysa sorun budur
```

Temizlik:

```bash
ps -eo pid,comm | grep -E "gz|ruby|rviz2|parameter_br|image_bridge|amcl|slam" \
  | grep -v grep | awk '{print $1}' | xargs -r kill -9
ros2 daemon stop && ros2 daemon start
```

> `Ctrl-C` ve `kill -TERM <launch pid>` yetmez: `setsid` ile ayrılan çocuk
> süreçler kendi oturumlarında hayatta kalır. Süreç grubunu öldürün
> (`kill -- -<pgid>`) veya yukarıdaki taramayı yapın.

### `ros2 node list` ölü düğümleri gösteriyor

ROS daemon'ının keşif önbelleği bayat. `ros2 daemon stop && ros2 daemon start`.

### Harita boş / AMCL "Waiting for map"

`map_server` haritayı yükleyememiştir. Logda `yaml-filename parameter is empty`
arayın. Nav2 parametrelerini `parameters=[dosya, {sözlük}]` ile ezmek
**çalışmaz** — dosyadaki değer kazanır. `RewrittenYaml` kullanılmalıdır
(navigation.launch.py'de öyle yapılıyor).

### Nav2 hedefi reddediyor

Hedef aslında kabul edilmiş ama istemci el sıkışmayı beklerken vazgeçmiş
olabilir. Logda `Failed to send goal response ... (timeout)` arayın; istemci
tarafındaki bekleme süresini artırın.

### `libEGL warning: egl: failed to create dri2 screen`

Hibrit grafik kartlarında olağan, zararsız. Render çalışıyor demektir; kontrol:

```bash
ros2 topic hz /scan          # ~10 Hz
ros2 topic hz /oak/rgb/image_raw
```

---

## 8. Gerçek robota geçiş — sıralı liste

1. **Ölç ve güncelle.** Gerçek robotun tekerlek yarıçapı, tekerlek arası ve
   LiDAR montaj konumunu ölçüp `astro.urdf.xacro`'ya yazın. Simülasyon bu
   değerleri izler.
2. **`ticks_per_rev` kalibre edin** (§6.1) ve `astro_params.yaml`'a yazın.
3. **`base_bridge` düğümünü yazın** (§4) — `/joint_states → /odom` + tf ve
   `/cmd_vel → /wheel_cmds`. Bu olmadan SLAM ve Nav2 çalışamaz.
4. **Odometriyi doğrulayın** (§6.2, §6.3). Simülasyondaki hata düzeyine
   yaklaşmadan SLAM'e geçmeyin.
5. **SLAM'i çalıştırın**: `use_sim_time:=false scan_topic:=/scan_filtered`.
   Mekânı gezip haritayı kaydedin.
6. **Nav2'yi çalıştırın**: `use_sim_time:=false map:=<kaydettiğiniz harita>`.
   İlk konumu RViz'de **2D Pose Estimate** ile verin.
7. **`acc_lim_*` değerlerini gerçek ivmeyle güncelleyin** (§5.5).

Adım 3 tamamlanana kadar simülasyonda geliştirmeye devam edilebilir; taşınacak
tek şey parametreler ve haritadır, kod değişmez.
