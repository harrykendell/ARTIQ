# ####
# class SinusoidalFrequencyModulation(ExpFragment):
#     def build_fragment(self):
#         """
#         Frequency modulation experiment

#         This ExpFragment just breaks out the functionality of:class:`.SUServoFrag`.
#         """

#         self.setattr_device("core")
#         self.setattr_device("fastino")
#         self.setattr_device("core_dma")
#         self.core: Core
#         self.fastino: Fastino
#         self.core_dma: Core

#         # Retrieve the laser to be modulated (default = 852 nm ECDL)

#         lasers = [dev.name for dev in VDrivenSupply.values() if dev.unit == "MHz"]
#         default = lasers[1]
#         self.setattr_argument("laser", EnumerationValue(lasers, default=default))
#         self.laser: str
#         # self.gain = VDrivenSupply[self.laser].gain
#         self.gain = 83.0 * MHz / V

#         if self.laser is not None:
#             current_config = VDrivenSupply[self.laser]
#         else:
#             current_config = VDrivenSupply[default]
#         self.setattr_fragment("setter", SetSupplies, [current_config], init=False)
#         self.setter: SetSupplies

#         # Unlock the laser
#         unlocks = [dev for dev in get_local_devices(self, TTLInOut) if "unlock" in dev]
#         default = unlocks[0]
#         self.setattr_argument("ttl", EnumerationValue(unlocks))  # ttl 5
#         self.ttl: str
#         if self.ttl is not None:
#             self.unlock_ttl: TTLInOut = self.get_device(self.ttl)
#         else:
#             self.unlock_ttl: TTLInOut = self.get_device(default)

#         # Experimental parameters

#         self.setattr_param(
#             name="f_dev",
#             param_class=FloatParam,
#             description="Frequency deviation",
#             default=100 * MHz,
#             unit="MHz",
#             min=0.0 * MHz,
#             max=210.0 * MHz,
#         )
#         self.f_dev: FloatParamHandle

#         self.setattr_param(
#             name="f_m",
#             param_class=FloatParam,
#             description="Modulation frequency",
#             default=10.0 * kHz,
#             unit="kHz",
#             min=0.0 * kHz,
#             max=100.0 * kHz,
#         )
#         self.f_m: FloatParamHandle

#         self.setattr_param(
#             name="N",
#             param_class=IntParam,
#             description="Samples per cycle",
#             default=64,
#             min=8,
#             max=64,
#         )
#         self.N: IntParamHandle

#         self.setattr_param(
#             name="V0",
#             param_class=FloatParam,
#             description="DC bias voltage",
#             default=0.0 * V,
#             unit="V",
#         )
#         self.V0: FloatParamHandle

#     @kernel
#     def run_once(self):
#         self.core.reset()

#         # Example Parameters
#         # N = 16                  # samples per cycle (typ. 16–64)
#         # f_m = 10 kHz            # modulation frequency (up to 100 kHz)
#         # f_dev = 166.55 MHz      # frequency deviation (up to ±210 MHz)

#         # Compute timing
#         samples_per_sec = (
#             self.N.get() * self.f_m.get()
#         )  # sample_rate ≤ 0.9e6 (safety margin)

#         # Precompute kernel-invariant timing
#         dt = 1.0 / samples_per_sec  # seconds between sample/ time-steps

#         # hardware timing constraints (use mu to avoid float drift)
#         step_mu = self.core.seconds_to_mu(dt)
#         assert (
#             step_mu > self.fastino.t_frame
#         )  # "Sample rate exceeds Fastino capability" - but check you cant go faster or anything

#         # Precompute phase step for efficiency
#         phase_step = 2.0 * np.pi / float(self.N.get())

#         #  Record DMA sequence
#         with self.core_dma.record("sine_wave"):
#             # phase = 0.0
#             start_mu = now_mu()
#             for i in range(self.N.get()):
#                 # t = i * self.dt
#                 phase = i * phase_step
#                 # f = self.f_dev.get() * np.sin(phase)
#                 # print(f" V = {f / self.gain} V")
#                 self.setter.set_outputs([self.f_dev.get() * np.sin(phase)])
#                 at_mu(start_mu + i * step_mu)

#         #  Play it back continuously
#         handle = self.core_dma.get_handle("sine_wave")
#         self.core.break_realtime()
#         for _ in range(6000):  # play it back (n x 1e3) times, then return
#             self.core_dma.playback_handle(handle)

#         self.core.break_realtime()
#         # Reset the laser
#         self.setter.set_to_defaults()
#         # Relock the laser

#         # if self.reset.get():
#         #     """
#         #     Relock an ECDL

#         #     Unpush and then after `time_to_shift` seconds, turn the TTL off
#         #     """
#         #     self.setter.set_to_defaults()
#         #     delay(self.time_to_shift.get())
#         #     self.unlock_ttl.off()
#         #     logging.warning("Relocking %s", self.laser)
#         # else:
#         #     pass


# Frequency_Modulation = make_fragment_scan_exp(SinusoidalFrequencyModulation)



   # Compute timing
        # samples_per_sec = (
        #     self.N.get() * self.f_m.get()
        # )  # sample_rate ≤ 0.9e6 (safety margin)

        # Precompute kernel-invariant timing
        # dt = 1.0 / samples_per_sec  # seconds between sample/ time-steps
        dt = 1.0 / float(self.N.get() * self.f_m.get())

        # # hardware timing constraints (use mu to avoid float drift)
        # t_frame_mu = self.fastino.t_frame
        # margin_mu = self.core.seconds_to_mu(0 * us)  # small safety margin
        # step_mu = max(self.core.seconds_to_mu(dt), t_frame_mu + margin_mu)

        # Precompute phase step for efficiency
        phase_step = (2.0 * np.pi * float(self.f_m.get()))/ float(self.N.get())

        #  Record DMA sequence
        with self.core_dma.record("sine_wave"):
            for i in range(self.N.get()):
                # Method  1: using phase step
                phase = i * phase_step
                self.setter.set_outputs([self.f_dev.get() * np.sin(phase)])
                delay_mu(0)

            # let the last write settle
            # delay_mu(t_frame_mu + margin_mu)