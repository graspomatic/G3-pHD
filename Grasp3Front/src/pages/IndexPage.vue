<script setup>
import { ref, shallowReactive, toRaw, watch } from "vue";
import { Modal } from "usemodal-vue3";
import { useWebSocket } from "@vueuse/core";

// URL of Flask and flask-sock (websocket) server
const pythonServer = "http://127.0.0.1:5000";
const wsServer = "ws://127.0.0.1:5000";

// global variable for holding current display status
let currentDisplayStatus = [];

// properties for toggling between plotting options
const plotOptionA = ref("one");
const OptionsVisible = ref(false); // options refers to dropdowns for display and shape
const wsConn = ref(false); // Used to indicate when connection to websocket is lost

// properties for modal used to add new display
const ModalIsVisible = ref(false);
const rMaxInput = ref("9");
const rAlwaysUpInput = ref("5");
const rMinInput = ref("3");
const pistonRInput = ref("1.2");
const pistonPitchInput = ref("3.4");

// properties of display
const circles = ref([]);
const displayA_options = ref(["A", "B", "C"]);
const displayA_selected = ref("");
const shapeA_options = ref(["A", "B", "C"]);
const shapeA_selected = ref("");

// colors for pistons
const colorDisplay = "#666";
const colorDown = "#666";
const colorUp = "#222";
const colorAlwaysUp = "#555";
const colorDisabled = "#711";
const colorDisabledLeakyPiston = "#734";
const colorDisabledLeakyGasket = "#743";
const colorDisabledBroken = "#700";
const colorDisabledDoesntFall = "#755";



var activePistons = "0"; // pistons which are currently up, set by input from websocket

// properties of SVG
const pistonSelected = ref(false);
let hap_disp_width = 500;
let hap_disp_height = hap_disp_width;
let center_x = hap_disp_width / 2;
let center_y = hap_disp_height / 2;

// message shown in badge in upper right corner of screen
const badgeMessage = ref("Loading...");

// error modal
const errorMessage = ref("");
const showErrorModal = ref(false);

function showError(message) {
  showErrorModal.value = true;
  errorMessage.value = message;
}

// websocket connection
const { status, data, send, open, close } = useWebSocket(wsServer, {
  autoReconnect: {},
  heartbeat: {
    interval: 10000,
  },
});

watch(data, (val) => {
  handleWSMessage(val);
}); // watch for changes in the variable 'data' and send it to handleWSMessage when we get it
watch(status, (val) => {
  wsConn.value = val != "CLOSED";
}); // watch for changes in websocket connection status. "false" when closed.

// Listen for incoming messages from the flask-sock server
function handleWSMessage(message) {
  if (message == "__pong__") {
    console.log("got a pong");
    return;
  }

  // only do something if we're in the auto-update mode
  if (plotOptionA.value == "two") {
    currentDisplayStatus = JSON.parse(message);
    console.log(currentDisplayStatus);

    // if the json has a activePIstons key, update the global variable accordingly
    if (currentDisplayStatus["activePistons"]) {
      activePistons = currentDisplayStatus["activePistons"];
    }

    // if the json has a activeShape key, update the display box accordingly
    if (currentDisplayStatus["activeShape"]) {
      // shapeA_selected.value = currentDisplayStatus["activeShape"];
    }

    // if the json has a activeDisplay key and it's different from current selection, update selection and display
    if (currentDisplayStatus["activeDisplay"]) {
      if (currentDisplayStatus["activeDisplay"] != displayA_selected.value) {
        console.log("received sock, on choice 2, changing display...");
        displayA_selected.value = currentDisplayStatus["activeDisplay"]; // changing this value SHOULD also call changeDisplay but it seems like it doesnt...
        changeDisplay(1);
      } else {
        console.log("received sock, on choice 2, not changing display...");
        updatePistons();
      }
    }

    // TODO: change selection boxes to match settings
    // TODO: if shape is custom, change shape to empty string or soemthing?
    // TODO: update display according to these received values
  }
}

// Get the list of available display IDs and send it to the input box
fetch(pythonServer + "/get_display_IDs")
  .then((response) => response.json())
  .then((data) => {
    displayA_options.value = JSON.parse(data.DisplayIDs);
    if ("error" in data) {
      badgeMessage.value = data.error.toString();
    } else {
      badgeMessage.value = "";
    }
  })
  .catch(() => {
    showError("Couldn't connect to python server!");
  });

// *************************** Server comm functions ***************************************

function createDisplay() {
  fetch(pythonServer + "/display/0/0", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    },
    body:
      "rMin=" +
      rMinInput.value +
      "&rAlwaysUp=" +
      rAlwaysUpInput.value +
      "&rMax=" +
      rMaxInput.value +
      "&pistonR=" +
      pistonRInput.value +
      "&pistonPitch=" +
      pistonPitchInput.value,
  })
    .then((response) => response.json())
    .then((data) => {
      displayA_options.value.push(data.displayID.toString());
      displayA_selected.value = data.displayID.toString();
      console.log("Added display " + data.displayID.toString());
    })
    .then((ModalIsVisible.value = false))
    .then(changeDisplay(0))
    .catch(() => {
      showError("Couldn't connect to python server!");
    });
}

function changeDisplay(passiveUpdate = 1) {
  // Change the display that is being plotted and update the shapes list box
  // passiveUpdate = 0 means server will reset active shape to 0
  // passiveUpdate = 1 is helpful when in auto-update mode so server doesnt reset shape

  if (displayA_selected.value == "") {
    console.log("no display selected");
    return;
  }

  console.log("changeDisplay to: " + displayA_selected.value);
  console.log("passiveUpdate: " + passiveUpdate);
  circles.value = []; // clear out the circles
  // initCircle(0, center_x, center_y, "25vw", colorDisplay); // draw circle for full display
  initCircle(0, center_x, center_y, hap_disp_width / 2, colorDisplay); // draw circle for full display
  // initCircle(1000, center_x, center_y, hap_disp_width / 8, colorDisplay); // draw circle for full display

  fetch(
    pythonServer + "/display/" + displayA_selected.value + "/" + passiveUpdate
  )
    .then((response) => response.json())
    .then((data) => drawHapticDisplay(data))
    .then(updateShapeIDs())
    .then(updatePistons())
    .catch(() => {
      showError("Couldn't connect to python server!");
    });
}

function createShape() {
  // Check to make sure we've chosen a display,
  //   create new shape for that display, update the shape id listbox
  if (displayA_selected.value === "") {
    console.log("You need to select a display first");
    return;
  }
  fetch(pythonServer + "/shape/0", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    },
    body: "displayID=" + displayA_selected.value,
  })
    .then((response) => response.json())
    .then((data) => {
      shapeA_options.value.push(data.newShape.toString());
      shapeA_selected.value = data.newShape.toString();
      console.log("Added shape " + data.newShape.toString());
    })
    .then(changeShape)
    .catch(() => {
      showError("Couldn't connect to python server!");
    });
}

function changeShape() {
  // Change the shape that is being plotted
  console.log("changeShape to: " + shapeA_selected.value);

  fetch(pythonServer + "/shape/" + shapeA_selected.value)
    .then((response) => response.json())
    .then((data) => {
      updatePistons(data.shape);

      if ("error" in data) {
        badgeMessage.value = data.error.toString();
      } else {
        badgeMessage.value = "";
      }
    })
    .catch(() => {
      showError("Couldn't connect to python server!");
      badgeMessage.value = "Couldn't connect to python server!";
    });
}

function resetShape() {
  // Set all pistons low
  changeDisplay(0);
  shapeA_selected.value = "";
  fetch(pythonServer + "/shape/0").catch(() => {
    showError("Couldn't connect to python server!");
  });
}

function updateShapeIDs() {
  // Get the list of available shape IDs for this display and send it to the input box
  fetch(pythonServer + "/get_shape_IDs/" + displayA_selected.value)
    .then((response) => response.json())
    .then((data) => {
      shapeA_options.value = JSON.parse(data.ShapeIDs);
      shapeA_selected.value = "";
    })
    .catch(() => {
      showError("Couldn't connect to python server!");
    });
}

// *************************** Drawing functions ***************************************

function drawHapticDisplay(dispData) {
  // Draw all the pistons for this display
  // dispData should include xys, nPins, rMin, rMax, pistonR
  var xys = JSON.parse(dispData.xys); // xy position of each piston
  var mmToSVGConstant = ((1 / dispData.rMax) * hap_disp_width) / 2.3; // conversion ratio considering size of haptic display and screen size
  var pistonRadius = dispData.pistonR * mmToSVGConstant; // radius of each piston for this display
  var vacRadius = dispData.rMin * mmToSVGConstant * 0.8;

  for (let i = 0; i < xys.length; i++) {
    // figure out what color this pin should be
    switch (xys[i][3]) {
      case -1:
        var color = colorDisabled;
        break; // these are disabled pistons
      case 0:
        var color = colorDown;
        break; // these are off pistons
      default:
        var color = colorAlwaysUp; // these pistons are always up when presenting
    }

    var thisID = xys[i][0];
    let thisX = center_x - xys[i][1] * mmToSVGConstant;
    let thisY = center_y - xys[i][2] * mmToSVGConstant;

    initCircle(thisID, thisX, thisY, pistonRadius, color);
  }
  console.log(xys.length + " pins ");

  // Create circle indicating vacuum port
  initCircle(-1, center_x, center_y, vacRadius, colorDisplay); // draw circle for full display
}

function updatePistons(shape) {
  // if we aren't sent shape, figure out if we just need to plot global variable activePistons
  if (shape === undefined) {
    if (plotOptionA.value == "two") {
      shape = '"' + activePistons + '"'; // add quote at beginning and ending because thats what happens when we get it from HTTP GET
      // If its really short, it probably is just default vals
      if (shape.length < 4) {
        return;
      }
      // only use activePistons when we're in the auto-update mode
    } else {
      return;
    }
  }
  // Removing the first and last characters (quotation marks)
  shape.slice(1);
  shape.slice(0, shape.length - 1);

  if (circles.value.length == 1) {
    console.log("we dont have any pistons drawn");
    return;
  }

  // step through string and grab 1 or 0 for each piston
  // skip 0th and last position because theyre quoatation marks
  for (var i = 0; i < shape.length; i++) {
    if (shape[i] == "0") {
      circles.value[i]["fill"] = colorDown;
    } else if (shape[i] == "1") {
      circles.value[i]["fill"] = colorUp;
    }
  }
}

function initCircle(thisid, x, y, r, color) {
  // Draw a circle with specified id, center, radius, and color
  // and add it to a list so those properties can be later modified
  circles.value.push({
    id: thisid,
    cx: x,
    cy: y,
    r: r,
    fill: color,
  });
}

function changePlotOption() {
  if (plotOptionA.value == "one") {
    console.log("Picking shape");
    OptionsVisible.value = false;
  } else if (plotOptionA.value == "two") {
    console.log("Auto-updating");
    OptionsVisible.value = true;
    changeDisplay(1);
  } else if (plotOptionA.value == "three") {
    console.log("Manual adjustment");
    OptionsVisible.value = true;
  }
}

function disablePiston(circleID) {
  pistonSelected.value = circleID.id
}

function handleDisablePiston(request) {

// this is the circle of the entire display...dont do anything
  if (pistonSelected.value == 0) {
    return;
  }

  // we're not in manual mode...dont do anything
  if (plotOptionA.value != "three") {
    showError("Switch to manual mode to control single pistons");
    return;
  }

  console.log(pistonSelected.value + " " + request)

  if (request == "enable") {
    var col = colorDown;
  } else if (request == "leakyPiston") {
    var col = colorDisabledLeakyPiston;
  } else if (request == "leakyGasket") {
    var col = colorDisabledLeakyGasket;
  } else if (request == "brokenPiston") {
    var col = colorDisabledBroken;
  } else if (request == "doesntFall") {
    var col = colorDisabledDoesntFall;
  }

  circles.value[pistonSelected.value]["fill"] = col;


}

function onPistonClick() {
  // Manually toggle piston

  console.log(pistonSelected.value.id);

  // this is the circle of the entire display...dont do anything
  if (pistonSelected.value.id == 0) {
    return;
  }

  // we're not in manual mode...dont do anything
  if (plotOptionA.value != "three") {
    showError("Switch to manual mode to control single pistons");
    return;
  }

  // If this piston is supposed to be disabled...dont do anything
  if (pistonSelected.value.fill == colorDisabled) {
    showError("This piston is disabled");
    return;
  }

  if (pistonSelected.value.fill != colorUp) {
    var dir = 1;
    var col = colorUp;
  } else {
    var dir = 0;
    var col = colorDown;
  }

  fetch(
    pythonServer +
      "/set_piston/" +
      displayA_selected.value +
      "/" +
      pistonSelected.value.id +
      "/" +
      dir
  )
    .then((response) => response.json())
    .then((data) => {
      if ("error" in data) {
        if (!badgeMessage.value) {
          showError(data.error.toString());
        }
        badgeMessage.value = data.error.toString();
      } else {
        console.log("Set piston " + data.PLCChan.toString());
        badgeMessage.value = "";
      }
      pistonSelected.value.fill = col;
    })
    .catch(() => {
      showError("Couldn't connect to python server!");
    });
}
</script>

<template>
  <div id="q-app" style="min-height: 100vh">
    <div class="q-pa-md">
      <div class="q-gutter-sm" style="max-width: 50vw">
        <q-badge v-if="badgeMessage" color="red" floating>{{
          badgeMessage
        }}</q-badge>

        <!-- Toggle button for choosing between Pick Shape, Auto-Update, and Manual modes -->
        <q-btn-toggle
          v-model="plotOptionA"
          push
          glossy
          dark
          spread
          size="2vh"
          toggle-color="primary"
          @update:model-value="changePlotOption"
          :options="[
            { value: 'one', slot: 'one' },
            { value: 'two', slot: 'two' },
            { value: 'three', slot: 'three' },
          ]"
        >
          <template v-slot:one>
            <div class="row items-center no-wrap">
              <div class="text-center">Pick<br />shape</div>
              <q-icon right name="extension"></q-icon>
            </div>
          </template>

          <template v-slot:two>
            <div class="row items-center no-wrap">
              <div class="text-center" :class="{ red: !wsConn }">
                Auto-<br />update
              </div>
              <q-icon :class="{ red: !wsConn }" right name="update"></q-icon>
            </div>
          </template>

          <template v-slot:three>
            <div class="row items-center no-wrap">
              <div class="text-center">Manual</div>
              <q-icon right name="upgrade"></q-icon>
            </div>
          </template>
        </q-btn-toggle>

        <!-- Draw display -->
        <svg @click="onPistonClick" style="height: 70vh; width: 50vw">
          <circle
            v-for="circle in circles"
            :key="circle"
            :cx="circle.cx"
            :cy="circle.cy"
            :r="circle.r"
            :fill="circle.fill"
            @click="pistonSelected = circle"
            @contextmenu.prevent="disablePiston(circle)"
          ></circle>
          <!-- draw arrows for vacuum port -->
          <path d="M197.007,48.479L139.348,0v28.623C63.505,32.538,3.006,95.472,3.006,172.271v27.741h40.099v-27.741 c0-54.682,42.527-99.614,96.243-103.47v28.156L197.007,48.479z"  transform="rotate(90 50 100) scale(0.22, 0.22) translate(850,-450)" fill="none" stroke="black" stroke-width="3"></path>
          <path d="M197.007,48.479L139.348,0v28.623C63.505,32.538,3.006,95.472,3.006,172.271v27.741h40.099v-27.741 c0-54.682,42.527-99.614,96.243-103.47v28.156L197.007,48.479z"  transform="rotate(90 50 100) scale(0.22, -0.22) translate(850,460)" fill="none" stroke="black" stroke-width="3"></path>
          <polygon points="202.654,101.327 161,66.304 161,82.911 0,82.911 0,119.744 161,119.744 161,136.35 " transform="rotate(90) scale(0.25, 0.25) translate(850,-1100)" fill="none" stroke="black" stroke-width="3"></polygon>
        </svg>

        <!-- Display selection box -->
        <q-select
          v-model="displayA_selected"
          :options="displayA_options"
          @update:model-value="changeDisplay(0)"
          filled
          :disable="OptionsVisible"
          bottom-slots
          label="Haptic Display"
          dark
        >
          <template v-slot:before><q-icon name="hexagon"></q-icon></template>
          <template v-slot:append>
            <q-btn
              round
              dense
              flat
              icon="add"
              @click="ModalIsVisible = true"
              @click.stop.prevent
            ></q-btn>
          </template>
        </q-select>

        <!-- Shape selection box -->
        <q-select
          v-model="shapeA_selected"
          :options="shapeA_options"
          @update:model-value="changeShape"
          filled
          :disable="OptionsVisible"
          bottom-slots
          label="Shape"
          dark
        >
          <template v-slot:before><q-icon name="extension"></q-icon></template>
          <template v-slot:append>
            <q-btn
              round
              dense
              flat
              icon="restart_alt"
              @click="resetShape"
              @click.stop.prevent
            ></q-btn>

            <q-btn
              round
              dense
              flat
              icon="add"
              @click="createShape"
              @click.stop.prevent
            ></q-btn>
          </template>
        </q-select>
      </div>
    </div>
  </div>

  <!-- Modal for creating new display -->
  <Modal
    v-model:visible="ModalIsVisible"
    title="Create new display"
    :okButton="{ text: 'Create', onclick: createDisplay }"
    :animation="true"
    :closable="false"
  >
    <div>
      <q-input v-model="rMaxInput" label="rMax"></q-input>
      <q-input v-model="rAlwaysUpInput" label="rAlwaysUp"></q-input>
      <q-input v-model="rMinInput" label="rMin"></q-input>
      <q-input v-model="pistonRInput" label="pistonR"></q-input>
      <q-input v-model="pistonPitchInput" label="pistonPitch"></q-input>
    </div>
  </Modal>

  <!-- Modal for showing error -->
  <q-dialog v-model="showErrorModal" position="bottom">
    <q-card style="width: 350px">
      <q-linear-progress :value="0.9" color="pink"></q-linear-progress>
      <q-card-section class="row items-center no-wrap">
        <div>
          <div class="text-weight-bold">Error</div>
          <div class="text-grey">
            <p>{{ errorMessage }}</p>
          </div>
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>

  <!-- Right click menu for enabling/disabling piston-->
  <q-menu touch-position context-menu>
    <q-list dense style="min-width: 100px">

      <q-item
              clickable
              v-close-popup
              @click="handleDisablePiston('enable')"
            >
        <q-item-section>Enable</q-item-section>
      </q-item>

      <q-item clickable>
        <q-item-section>Disable</q-item-section>
        <q-item-section side>
          <q-icon name="keyboard_arrow_right"></q-icon>
        </q-item-section>

        <q-menu anchor="top end" self="top start">
          <q-list dense>
            <q-item
              clickable
              v-close-popup
              @click="handleDisablePiston('leakyPiston')"
            >
              <q-item-section>Leaky piston</q-item-section>
            </q-item>
            <q-item
              clickable
              v-close-popup
              @click="handleDisablePiston('leakyGasket')"
            >
              <q-item-section>Leaky gasket</q-item-section>
            </q-item>
            <q-item
              clickable
              v-close-popup
              @click="handleDisablePiston('brokenPiston')"
            >
              <q-item-section>Broken piston</q-item-section>
            </q-item>
            <q-item
              clickable
              v-close-popup
              @click="handleDisablePiston('doesntFall')"
            >
              <q-item-section>Doesnt fall</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-item>
    </q-list>
  </q-menu>
</template>

<style>
body {
  margin: 0;
  overflow: auto;
  background-color: rgb(40, 40, 40);
}

svg {
  width: 50vh;
  height: 50vh;
  background-color: rgb(40, 40, 40);
}

circle {
  stroke: rgb(40, 40, 40);
}

/* used to indicate no connection to server on AUTO-UPDATE button */
.red {
  color: red;
}
</style>
